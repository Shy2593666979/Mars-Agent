import asyncio
import inspect
import json
import time
import logging
from typing import List, Dict, Any

from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, SystemMessage, ToolCall, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.constants import START, END
from langgraph.graph import StateGraph, MessagesState

from mars_agent.core.models.manager import MarsModelManager
from mars_agent.prompts.chat_prompt import DEFAULT_CALL_PROMPT
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.util import mcp_tool_to_args_schema, convert_langchain_tool_calls
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEP = 5

class MCPAgent:
    """MCPAgent

    Lightweight sub-agent dedicated to executing **MCP (Multi-Channel Plugin) tools**.  It turns every
    endpoint provided by your MCP servers into a LangChain ``BaseTool`` and decides – step by step –
    whether and when the tool should be invoked.

    Responsibilities
    ---------------
    1. Establish HTTP/SSE connection to each configured MCP server and collect its tool schema.
    2. Decide which MCP tool(s) should be called according to the latest conversation messages.
    3. Execute the selected tool(s) asynchronously and forward their results to the shared
       ``EventManager`` so that the main :class:`mars_agent.agent.MarsAgent` can aggregate them.
    4. **No natural-language reply is generated here.**  Text generation responsibilities live in the
       parent agent.

    Usage
    -----
    End-users normally do **not** instantiate this class directly.  A ``MCPAgent`` will be created
    automatically by :class:`mars_agent.agent.MarsAgent` when ``mcp_as_agent`` is set to ``True``.
    """
    
    def __init__(self,
                 mcp_config: MCPBaseConfig,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 event_queue: asyncio.Queue = None):

        self.mcp_config = mcp_config
        self.mcp_manager = MCPManager([mcp_config])
        self.event_queue = event_queue

        # Use main agent's event queue, events automatically reported to main agent
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()

        self.mcp_tools: List[BaseTool] = []
        # Sub-agent only needs tool calling model, not conversation model
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.graph = None
        self.step_counter = 0
        self.step_counter_lock = asyncio.Lock()
        self._initialized = False

    async def emit_event(self, data: Dict[Any, Any]):
        """Sub-agent event sending - automatically report to main agent"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )

    async def init_mcp_agent(self):
        """Initialize MCP Agent - with resource management"""
        try:
            if self._initialized:
                logger.info(f"MCP Agent {self.mcp_config.server_name} already initialized")
                return

            if self.mcp_config:
                self.mcp_tools = await self.set_mcp_tools()

            await self.set_agent_graph()
            self._initialized = True
            logger.info(f"MCP Agent {self.mcp_config.server_name} initialized successfully")
            
        except Exception as err:
            logger.error(f"Failed to initialize MCP Agent {self.mcp_config.server_name}: {err}")
            raise

    async def set_mcp_tools(self):
        """Get MCP tools"""
        try:
            mcp_tools = await self.mcp_manager.get_mcp_tools()
            return mcp_tools
        except Exception as err:
            logger.error(f"Failed to get MCP tools: {err}")
            return []

    async def call_tools_messages(self, messages: List[BaseMessage]) -> AIMessage:
        """MCP tool selection - sub-agent responsible for MCP tool calling decision"""
        SELECT_TOOL_MESSAGE = EventTitleType.SELECT_TOOL if self.step_counter == 1 else EventTitleType.CONTINUE_SELECT_TOOL

        call_tool_messages: List[BaseMessage] = []

        # Send MCP tool analysis start event to main agent
        await self.event_manager.emit_progress(
            SELECT_TOOL_MESSAGE,
            EventMessageType.ANALYZING_MCP_TOOLS.format(server_name=self.mcp_config.server_name),
            EventStatusType.START,
            EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
        )

        # Only initialize when calling tools for the first time
        if self.step_counter == 0:
            tools_schema = []
            for tool in self.mcp_tools:
                tools_schema.append(mcp_tool_to_args_schema(tool.name, tool.description, tool.args_schema))

            self.tool_invocation_model.bind_tools(tools_schema)

            system_message = SystemMessage(content=DEFAULT_CALL_PROMPT)
            # MCP Agent separate Prompt, not affected by history
            call_tool_messages.append(system_message)
            call_tool_messages.append(messages[-1])
        else:
            system_message = SystemMessage(content=DEFAULT_CALL_PROMPT)
            call_tool_messages.append(system_message)
            call_tool_messages.extend(messages)

        response = await self.tool_invocation_model.ainvoke(call_tool_messages)
        # Determine if there are tools available for calling
        if response.tool_calls:
            openai_tool_calls = response.tool_calls
            response.tool_calls = convert_langchain_tool_calls(response.tool_calls)

            tool_call_names = [tool_call["name"] for tool_call in response.tool_calls]
            # Send MCP tool selection completion event to main agent
            await self.event_manager.emit_progress(
                SELECT_TOOL_MESSAGE,
                EventMessageType.AVAILABLE_MCP_TOOL.format(server_name=self.mcp_config.server_name, tool_name=", ".join(set(tool_call_names))),
                EventStatusType.END,
                EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
            )

            return AIMessage(
                content="Available tools found",
                tool_calls=response.tool_calls,
            )
        else:
            await self.event_manager.emit_progress(
                SELECT_TOOL_MESSAGE,
                EventMessageType.NO_AVAILABLE_TOOL,
                EventStatusType.ERROR,
                EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
            )

            # Send no MCP tools available event to main agent
            return AIMessage(content="No available tools found")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """MCP tool execution - sub-agent responsible for specific MCP tool execution"""
        tool_calls = messages[-1].tool_calls
        tool_messages: List[BaseMessage] = []

        for tool_call in tool_calls:
            # Ensure no race conditions occur
            async with self.step_counter_lock:
                self.step_counter += 1

            mcp_tool = self.find_mcp_tool(tool_call["name"])
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]
            try:
                # For authenticated MCP Servers, user's separate configuration is required, e.g. Feishu, email
                if self.mcp_config.personal_config:
                    tool_args.update(self.mcp_config.personal_config)

                # Send MCP tool execution start event to main agent
                await self.event_manager.emit_progress(
                    EventTitleType.EXECUTE_MCP_TOOL.format(tool_name=tool_name),
                    EventMessageType.CALL_MCP_TOOL.format(tool_name=tool_name),
                    EventStatusType.START,
                    EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
                )

                # Call MCP tool to return all results, but currently only handle text data
                text_content, no_text_content = await mcp_tool.coroutine(**tool_args)

                # Send MCP tool execution completion event to main agent
                await self.event_manager.emit_progress(
                    EventTitleType.EXECUTE_MCP_TOOL.format(tool_name=tool_name),
                    text_content,
                    EventStatusType.END,
                    EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
                )

                tool_messages.append(
                    ToolMessage(content=text_content, name=tool_name, tool_call_id=tool_call_id))
                logger.info(f"MCP Tool {tool_name}, Args: {tool_args}, Result: {text_content}")

            except Exception as err:
                # Send MCP tool execution error event to main agent
                await self.event_manager.emit_event(
                    self.event_manager.create_event(
                        EventType.ERROR,
                        {
                            "title": EventTitleType.EXECUTE_MCP_TOOL.format(tool_name=tool_name),
                            "message": EventMessageType.TOOL_ERROR.format(err=str(err)),
                            "status": EventStatusType.ERROR
                        }
                    )
                )

                logger.error(f"MCP Tool {tool_name} Error: {str(err)}")
                tool_messages.append(
                    ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages

    async def set_agent_graph(self):
        """Set up MCP Agent's tool execution graph"""

        # Build tool calling Graph
        async def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]

            # If tool recursive calls exceed DEFAULT_MAX_STEP times, return END directly
            if self.step_counter > DEFAULT_MAX_STEP:
                return END

            if last_message.tool_calls:
                return "execute_tool_node"
            else:
                return END

        async def call_tool_node(state: MessagesState):
            messages = state["messages"]
            tool_message = await self.call_tools_messages(messages)
            messages.append(tool_message)

            return {"messages": messages}

        async def execute_tool_node(state: MessagesState):
            messages = state["messages"]

            tool_results = await self.execute_tool_message(messages)
            messages.extend(tool_results)

            return {"messages": messages}

        workflow = StateGraph(MessagesState)

        workflow.add_node("call_tool_node", call_tool_node)
        workflow.add_node("execute_tool_node", execute_tool_node)

        # Set start node
        workflow.add_edge(START, "call_tool_node")
        # Set edge to determine whether to call tools
        workflow.add_conditional_edges("call_tool_node", should_continue)
        # Detect if tool recursion information exists
        workflow.add_edge("execute_tool_node", "call_tool_node")

        self.graph = workflow.compile()

    async def ainvoke(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """MCP Agent tool execution - only return MCP tool execution results, no model reply"""
        if not self._initialized:
            await self.init_mcp_agent()

        # Send MCP Agent start working event
        await self.event_manager.emit_progress(
            EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name),
            EventMessageType.MCP_AGENT_STARTING,
            EventStatusType.START,
            EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
        )
        
        try:
            result = await self.graph.ainvoke({"messages": messages})
            messages = []
            for message in result["messages"][:-1]: # Remove AIMessage that didn't hit tools
                if not isinstance(message, HumanMessage) and not isinstance(message, SystemMessage):
                    messages.append(message)
            
            # Send MCP Agent work completion event
            tool_count = len([msg for msg in messages if isinstance(msg, ToolMessage)])
            completion_message = EventMessageType.MCP_AGENT_COMPLETED.format(tool_count=tool_count) if tool_count > 0 else EventMessageType.MCP_AGENT_NO_TOOLS
            await self.event_manager.emit_progress(
                EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name),
                completion_message,
                EventStatusType.END,
                EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name)
            )
            
            return messages
            
        except Exception as err:
            logger.error(f"MCP Agent {self.mcp_config.server_name} execution failed: {err}")
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": EventAgentType.MCP_AGENT.format(server_name=self.mcp_config.server_name),
                        "message": EventMessageType.EXECUTION_FAILED.format(err=str(err)),
                        "status": EventStatusType.ERROR
                    }
                )
            )
            return []

    def find_mcp_tool(self, name) -> BaseTool | None:
        """Find MCP tool by name"""
        for tool in self.mcp_tools:
            if tool.name == name:
                return tool
        return None





