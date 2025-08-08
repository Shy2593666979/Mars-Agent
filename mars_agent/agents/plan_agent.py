import asyncio
import json
import logging
from collections.abc import Awaitable
from typing import Callable, Union, List

from langchain_core.messages import SystemMessage, BaseMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.tools import Tool

from mars_agent import MarsModelConfig
from mars_agent.prompts.chat_prompt import _PLAN_CALL_TOOL_PROMPT, _FIX_JSON_PROMPT, _SINGLE_PLAN_CALL_PROMPT
from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.utils import function_to_args_schema, EventManager, EventType, convert_langchain_tool_calls

logger = logging.getLogger(__name__)

class PlanAgent:

    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 event_queue: asyncio.Queue = None):

        self.functions = functions

        if not tool_call_model_config:
            self.tool_call_model_config = model_config
        else:
            self.tool_call_model_config = tool_call_model_config

        self.model_config = model_config

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



    async def plan_agent_actions(self, messages: List[BaseMessage]):
        """pass"""
        await self.init_plugin_tools()
        call_messages: List[BaseMessage] = []

        call_messages.append(messages[-1])
        call_messages.append(SystemMessage(content=_PLAN_CALL_TOOL_PROMPT.format(user_query=messages[-1].content, tools_info = "\n\n".join([str(tool_schema) for tool_schema in self.plugin_tools_schema]))))

        response = await self.conversation_model.ainvoke(call_messages)

        try:
            content = json.loads(response.content)
            self.agent_plans = content
            return content
        except Exception as err:
            # 发送对JSON 数据开始修复的信息

            fix_message = HumanMessage(content=_FIX_JSON_PROMPT.format(json_content=response.content, json_error=str(err)))
            fix_response = await self.conversation_model.ainvoke([fix_message])

            try:
                fix_content = fix_response.content
                self.agent_plans = fix_content
                return fix_content
            except Exception as fix_err:
                # 发送Json数据不可修复的信息

                raise ValueError(fix_err)


    async def call_tools_message(self, agent_plans: dict) -> List[BaseMessage]:
        self.tool_call_model.bind_tools(self.plugin_tools_schema)

        tool_results: List[BaseMessage] = []
        for step, plan in agent_plans.items():
            # 为每次调用准备不同的提示词
            call_tool_messages = []
            system_message = HumanMessage(content=_SINGLE_PLAN_CALL_PROMPT.format(plan_actions=str(plan)))
            call_tool_messages.append(system_message)
            call_tool_messages.extend(tool_results)

            response = await self.tool_call_model.ainvoke(call_tool_messages)
            # Determine if there are tools available for calling
            if response.tool_calls:
                openai_tool_calls = response.tool_calls
                response.tool_calls = convert_langchain_tool_calls(response.tool_calls)

                ai_message = AIMessage(
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            else:
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
                    EventTitleType.EXECUTE_PLUGIN_TOOL.format(tool_name=tool_name),
                    EventMessageType.CALL_PLUGIN_TOOL.format(tool_name=tool_name),
                    EventStatusType.START,
                    EventAgentType.PLAN_AGENT
                )

                if hasattr(use_tool, "coroutine") and use_tool.coroutine is not None:
                    tool_result = await use_tool.coroutine(**tool_args)
                else:
                    # Convert to async
                    tool_result = await asyncio.to_thread(use_tool.func, **tool_args)

                # Send plugin tool execution completion event to main agent
                await self.event_manager.emit_progress(
                    EventTitleType.EXECUTE_PLUGIN_TOOL.format(tool_name=tool_name),
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
                            "title": EventTitleType.EXECUTE_PLUGIN_TOOL.format(tool_name=tool_name),
                            "message": EventMessageType.TOOL_ERROR.format(err=str(err)),
                            "status": EventStatusType.ERROR
                        }
                    )
                )

                logger.error(f"Plugin Tool {tool_name} Error: {str(err)}")
                tool_messages.append(
                    ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages

    def find_tool_use(self, tool_name: str):
        """Determine if it's an MCP tool and return the corresponding tool instance"""
        for tool in self.plugin_tools:
            if tool.name == tool_name:
                return False, tool

        raise ValueError(f"Tool does not exist in the system: {tool_name}")

    async def ainvoke(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
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
            yield event

        tool_results = await run_plan_task
        messages.extend(tool_results)

        async for chunk in self.conversation_model.astream(messages):
            yield chunk
