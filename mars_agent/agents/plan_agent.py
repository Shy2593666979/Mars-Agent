import asyncio
import json
import logging
from collections.abc import Awaitable
from typing import Callable, Union, List

from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.tools import Tool

from mars_agent.schema import MarsModelConfig, MCPBaseConfig
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.prompts.chat_prompt import _FIX_JSON_PROMPT, _SINGLE_PLAN_CALL_PROMPT, \
    PLAN_CALL_TOOL_PROMPT
from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType, \
    PlanType
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.utils import function_to_args_schema, EventManager, EventType, convert_langchain_tool_calls, \
    mcp_tool_to_args_schema
from mars_agent.utils.util import get_current_time

logger = logging.getLogger(__name__)

CALL_USER = "request_missing_param"


class MarsPlanAgent:

    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 mcp_configs: List[MCPBaseConfig] = [],
                 enable_runtime_logs: bool = True,
                 event_queue: asyncio.Queue = None):

        self.mcp_tools_schema = []
        self.functions = functions

        if not tool_call_model_config:
            self.tool_call_model_config = model_config
        else:
            self.tool_call_model_config = tool_call_model_config

        self.model_config = model_config

        self.enable_runtime_logs = enable_runtime_logs

        self.mcp_configs = mcp_configs
        self.mcp_manager = MCPManager(mcp_configs)

        self.event_queue = event_queue
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()

        self.agent_plans: dict = {}

        self.tool_call_model = MarsModelManager.get_tool_call_model(self.tool_call_model_config)
        self.conversation_model = MarsModelManager.get_conversation_model(self.model_config)

    async def init_plugin_tools(self):
        """Initialize plugin tools - with error handling"""
        self.plugin_tools = []
        self.plugin_tools_schema = []

        # Meaningless function, but Tool needs a func
        def _t():
            pass

        try:
            for func in self.functions:
                self.plugin_tools_schema.append(function_to_args_schema(func))

                if asyncio.iscoroutinefunction(func):
                    self.plugin_tools.append(
                        Tool(name=func.__name__, description=func.__doc__, func=_t, coroutine=func))
                else:
                    self.plugin_tools.append(Tool(name=func.__name__, description=func.__doc__, func=func))

            logger.info(f"Loaded {len(self.plugin_tools)} plugin tools")
        except Exception as err:
            logger.error(f"Failed to initialize plugin tools: {err}")
            self.plugin_tools = []

    async def init_mcp_tools(self):
        """Initialize MCP tools - with error handling"""
        if not self.mcp_configs:
            self.mcp_tools = []
            return

        try:
            # Establish connection with MCP Server
            self.mcp_tools = await self.mcp_manager.get_mcp_tools()

            mcp_servers_info = await self.mcp_manager.show_mcp_tools()
            self.server_dict = {server_name: [tool["name"] for tool in tools_info] for server_name, tools_info in
                                mcp_servers_info.items()}

            for mcp_tool in self.mcp_tools:
                self.mcp_tools_schema.append(
                    mcp_tool_to_args_schema(mcp_tool.name, mcp_tool.description, mcp_tool.args_schema))

            logger.info(f"Loaded {len(self.mcp_tools)} MCP tools from MCP servers")

        except Exception as err:
            logger.error(f"Failed to initialize MCP tools: {err}")
            self.mcp_tools = []

    async def plan_agent_actions(self, messages: List[BaseMessage]):
        """pass"""
        await self.init_plugin_tools()
        await self.init_mcp_tools()

        # Send the start message for generating tool call planning
        await self.event_manager.emit_progress(
            EventTitleType.PLAN_ACTIONS,
            EventMessageType.START_TOOLS_PLAN,
            EventStatusType.START,
            EventAgentType.PLAN_AGENT
        )

        call_messages: List[BaseMessage] = []
        call_messages.extend(messages)

        if isinstance(call_messages[0], SystemMessage):
            call_messages[0] = SystemMessage(
                content=PLAN_CALL_TOOL_PROMPT.format(user_query=messages[-1].content, current_time=get_current_time(),
                                                     tools_info="\n\n".join([str(tool_schema) for tool_schema in
                                                                             self.plugin_tools_schema + self.mcp_tools_schema])))
        else:
            call_messages.insert(0, SystemMessage(content=PLAN_CALL_TOOL_PROMPT.format(user_query=messages[-1].content, current_time=get_current_time(), tools_info="\n\n".join([str(tool_schema) for tool_schema in self.plugin_tools_schema + self.mcp_tools_schema]))))

        response = await self.conversation_model.ainvoke(call_messages)

        try:
            content = json.loads(response.content)
            self.agent_plans = content

            # Send the success message for tool call planning generation
            await self.event_manager.emit_progress(
                EventTitleType.PLAN_ACTIONS,
                EventMessageType.END_TOOLS_PLAN.format(content=content),
                EventStatusType.END,
                EventAgentType.PLAN_AGENT
            )

            return content
        except Exception as err:
            # Send the error message for parsing model output
            await self.event_manager.emit_progress(
                EventTitleType.PLAN_ACTIONS,
                EventMessageType.TOOLS_PLAN_ERROR.format(err=err),
                EventStatusType.ERROR,
                EventAgentType.PLAN_AGENT
            )

            # Send the start message for JSON data repair
            await self.event_manager.emit_progress(
                EventTitleType.FIX_PLAN_JSON,
                EventMessageType.START_FIX_JSON,
                EventStatusType.START,
                EventAgentType.PLAN_AGENT
            )

            fix_message = HumanMessage(
                content=_FIX_JSON_PROMPT.format(json_content=response.content, json_error=str(err)))
            fix_response = await self.conversation_model.ainvoke([fix_message])

            try:
                fix_content = json.loads(fix_response.content)
                self.agent_plans = fix_content
                # Send the completion message for JSON data repair
                await self.event_manager.emit_progress(
                    EventTitleType.FIX_PLAN_JSON,
                    EventMessageType.END_FIX_JSON.format(fix_content=fix_content),
                    EventStatusType.END,
                    EventAgentType.PLAN_AGENT
                )

                return fix_content
            except Exception as fix_err:
                # Send the message for irreparable JSON data
                await self.event_manager.emit_progress(
                    EventTitleType.FIX_PLAN_JSON,
                    EventMessageType.FIX_JSON_ERROR.format(err=err),
                    EventStatusType.ERROR,
                    EventAgentType.PLAN_AGENT
                )

                raise ValueError(fix_err)

    async def call_tools_message(self, agent_plans: dict) -> List[BaseMessage]:
        self.tool_call_model.bind_tools(self.plugin_tools_schema + self.mcp_tools_schema)

        # Send tool analysis start event to plan agent
        await self.event_manager.emit_progress(
            EventTitleType.SELECT_TOOL,
            EventMessageType.ANALYZING_TOOLS,
            EventStatusType.START,
            EventAgentType.PLAN_AGENT
        )

        tool_results: List[BaseMessage] = []
        for step, plan in agent_plans.items():
            if plan[0].get(PlanType.TOOL_NAME) == PlanType.CALL_USER:
                tool_results.append(AIMessage(content=str(plan)))
                break

            # Prepare different prompts for each call
            call_tool_messages = []
            system_message = HumanMessage(content=_SINGLE_PLAN_CALL_PROMPT.format(plan_actions=str(plan)))
            call_tool_messages.append(system_message)
            call_tool_messages.extend(tool_results)

            response = await self.tool_call_model.ainvoke(call_tool_messages)
            # Determine if there are tools available for calling
            if response.tool_calls:
                openai_tool_calls = response.tool_calls
                response.tool_calls = convert_langchain_tool_calls(response.tool_calls)

                tool_call_names = [tool_call["name"] for tool_call in response.tool_calls]

                # Send tool selection completion event to plan agent
                await self.event_manager.emit_progress(
                    EventTitleType.SELECT_TOOL,
                    EventMessageType.AVAILABLE_TOOLS.format(tool_name=", ".join(set(tool_call_names))),
                    EventStatusType.END,
                    EventAgentType.PLAN_AGENT
                )

                ai_message = AIMessage(
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            else:
                # Send no tools available event to plan agent
                await self.event_manager.emit_progress(
                    EventTitleType.SELECT_TOOL,
                    EventMessageType.NO_AVAILABLE_TOOL,
                    EventStatusType.END,
                    EventAgentType.PLAN_AGENT
                )

                # Send no tools available event to main agent
                ai_message = AIMessage(content="No available tools found")

            tool_messages = await self.execute_tool_message(ai_message)
            tool_results.append(ai_message)
            tool_results.extend(tool_messages)

        return tool_results

    async def execute_tool_message(self, message: AIMessage):
        """Tool execution - sub-agent responsible for specific tool execution"""
        tool_calls = message.tool_calls
        tool_messages: List[BaseMessage] = []

        for tool_call in tool_calls:

            is_mcp_tool, use_tool = self.find_tool_use(tool_call["name"])
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]

            try:

                # Send plugin tool invocation event to main agent
                await self.event_manager.emit_progress(
                    EventTitleType.EXECUTE_TOOL.format(tool_name=tool_name),
                    EventMessageType.CALL_TOOL.format(tool_name=tool_name),
                    EventStatusType.START,
                    EventAgentType.PLAN_AGENT
                )

                if hasattr(use_tool, "coroutine") and use_tool.coroutine is not None:
                    # Determine if user personal configuration needs to be added
                    if is_mcp_tool:
                        personal_config = self.get_mcp_config_by_tool(tool_name)
                        tool_args.update(personal_config)

                    tool_result, _ = await use_tool.coroutine(**tool_args)
                else:
                    # Convert to async
                    tool_result = await asyncio.to_thread(use_tool.func, **tool_args)

                # Send plugin tool execution completion event to main agent
                await self.event_manager.emit_progress(
                    EventTitleType.EXECUTE_TOOL.format(tool_name=tool_name),
                    tool_result,
                    EventStatusType.END,
                    EventAgentType.PLAN_AGENT
                )

                tool_messages.append(
                    ToolMessage(content=tool_result, name=tool_name, tool_call_id=tool_call_id))
                logger.info(f"Plugin Tool {tool_name}, Args: {tool_args}, Result: {tool_result}")

            except Exception as err:
                # Send plugin tool execution error event to main agent
                await self.event_manager.emit_event(
                    self.event_manager.create_event(
                        EventType.ERROR,
                        {
                            "title": EventTitleType.EXECUTE_TOOL.format(tool_name=tool_name),
                            "message": EventMessageType.TOOL_ERROR.format(err=str(err)),
                            "status": EventStatusType.ERROR
                        }
                    )
                )

                logger.error(f"Plugin Tool {tool_name} Error: {str(err)}")
                tool_messages.append(
                    ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages

    # Additional helper methods
    def find_tool_use(self, tool_name: str):
        """Determine if it's an MCP tool and return the corresponding tool instance"""
        for tool in self.mcp_tools:
            if tool.name == tool_name:
                return True, tool

        for tool in self.plugin_tools:
            if tool.name == tool_name:
                return False, tool

        raise ValueError(f"Tool does not exist in the system: {tool_name}")

    # Get MCP Server's user config
    def get_mcp_config_by_tool(self, tool_name):
        for server_name, tools in self.server_dict.items():
            if tool_name not in tools:
                continue

            for config in self.mcp_configs:
                if server_name == config.server_name:
                    return config.personal_config or {}
        return {}

    async def astream(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        async def run_plan_agent():
            agent_plans = await self.plan_agent_actions(messages)
            if agent_plans:
                tool_results = await self.call_tools_message(agent_plans)
                return tool_results
            else:
                return []

        run_plan_task = asyncio.create_task(run_plan_agent())

        async for event in self.event_manager.stream_with_heartbeat([run_plan_task]):
            if self.enable_runtime_logs:
                yield event

        tool_results = await run_plan_task
        messages.extend(tool_results)

        # Plan agent is responsible for final model reply streaming
        response_content = ""
        try:
            # Send model reply start event
            await self.event_manager.emit_progress(
                EventTitleType.MODEL_RESPONSE,
                EventMessageType.GENERATING_RESPONSE,
                EventStatusType.START,
                EventAgentType.PLAN_AGENT
            )

            async for chunk in self.conversation_model.astream(messages):
                if chunk.content:
                    response_content += chunk.content
                    # Plan agent uniformly handles response chunk events
                    yield self.event_manager.create_response_chunk_event(chunk.content, response_content)

            # Send model reply completion event
            await self.event_manager.emit_progress(
                EventTitleType.MODEL_RESPONSE,
                EventMessageType.RESPONSE_COMPLETED,
                EventStatusType.END,
                EventAgentType.MARS_AGENT
            )

        # Plan agent uniformly handles errors
        except Exception as err:
            logger.error(f"LLM Model Error: {err}")
            # Send error event
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": EventTitleType.MODEL_RESPONSE_ERROR,
                        "message": EventMessageType.TOOL_ERROR.format(err=str(err)),
                        "status": EventStatusType.ERROR
                    }
                )
            )
            # Send fallback reply
            yield self.event_manager.create_response_chunk_event(
                "Your question touches my knowledge blind spot, please try a different question ✨",
                response_content
            )

    async def ainvoke(self, messages: Union[str, BaseMessage, List[BaseMessage]]) -> AIMessage:
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        async def run_plan_agent():
            agent_plans = await self.plan_agent_actions(messages)
            if agent_plans:
                tool_results = await self.call_tools_message(agent_plans)
                return tool_results
            else:
                return []

        run_plan_task = asyncio.create_task(run_plan_agent())

        tool_results = await run_plan_task
        messages.extend(tool_results)

        response = await self.conversation_model.ainvoke(messages)
        return AIMessage(content=response.content)
