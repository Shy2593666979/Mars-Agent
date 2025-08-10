import asyncio
import copy
import json
import time
import inspect
import logging
from typing import List, Dict, Any, Callable, Union
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, ToolMessage, HumanMessage, ToolCall
from langchain_core.tools import BaseTool, Tool
from langgraph.graph import MessagesState, StateGraph, END, START
from collections.abc import Awaitable

from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.prompts.chat_prompt import DEFAULT_CALL_PROMPT
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.util import convert_langchain_tool_calls, function_to_args_schema, mcp_tool_to_args_schema
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)

class StreamingAgent:
    """StreamingAgent

    Sub-agent that can invoke **both user-provided plugin functions and MCP tools**.  It analyses the
    current conversation, decides which tool(s) should be run, performs the calls asynchronously and
    pushes progress/result events back to the main :class:`mars_agent.agent.MarsAgent`.

    Responsibilities
    ---------------
    1. Select appropriate plugin or MCP tool according to conversation context.
    2. Execute the tool in an asynchronous, non-blocking way.
    3. Report every progress, success or error through the shared ``EventManager``.
    4. **Does not generate any LLM response** – that task belongs to the main agent.

    Usage
    -----
    ``StreamingAgent`` instances are automatically created by :class:`mars_agent.agent.MarsAgent`.
    End-users rarely need to touch this class directly.
    """
    
    def __init__(self,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 mcp_configs: List[MCPBaseConfig] = [],
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 event_queue: asyncio.Queue = None):

        # Sub-agent only needs tool calling model, not conversation model
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.plugin_tools = []
        self.mcp_tools = []
        self.graph = None
        self.mcp_configs = mcp_configs
        self.tools = []
        self.mcp_manager = MCPManager(mcp_configs)
        self.functions = functions

        # Use main agent's event queue, events automatically reported to main agent
        self.event_queue = event_queue
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()
        self.step_counter_lock = asyncio.Lock()
        self.step_counter = 1

        # Record tool call count
        self.tool_call_count: dict[str, int] = {}

        # Find user config by server name
        self.server_dict: dict[str, Any] = {}
        
        # Initialize state management
        self._initialized = False


    async def emit_event(self, data: Dict[Any, Any]):
        """Sub-agent event sending - automatically report to main agent"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )

    async def init_stream_agent(self):
        """Initialize sub-agent - with resource management"""
        try:
            if self._initialized:
                logger.info("Stream Agent already initialized")
                return
                
            await self.set_agent_graph()
            await self.init_mcp_tools()
            await self.init_plugin_tools()

            self.tools = self.plugin_tools + self.mcp_tools
            self._initialized = True
            logger.info("Stream Agent initialized successfully")
            
        except Exception as err:
            logger.error(f"Failed to initialize Stream Agent: {err}")
            raise

    async def init_mcp_tools(self):
        """Initialize MCP tools - with error handling"""
        if not self.mcp_configs:
            self.mcp_tools = []
            return
            
        try:
            # Establish connection with MCP Server
            self.mcp_tools = await self.mcp_manager.get_mcp_tools()

            mcp_servers_info = await self.mcp_manager.show_mcp_tools()
            self.server_dict = {server_name: [tool["name"] for tool in tools_info] for server_name, tools_info in mcp_servers_info.items()}

            logger.info(f"Loaded {len(self.mcp_tools)} MCP tools from MCP servers")
                
        except Exception as err:
            logger.error(f"Failed to initialize MCP tools: {err}")
            self.mcp_tools = []

    async def init_plugin_tools(self):
        """Initialize plugin tools - with error handling"""
        self.plugin_tools = []

        # Meaningless function, but Tool needs a func
        def _t():
            pass

        try:
            for func in self.functions:
                if asyncio.iscoroutinefunction(func):
                    self.plugin_tools.append(Tool(name=func.__name__, description=func.__doc__, func=_t, coroutine=func))
                else:
                    self.plugin_tools.append(Tool(name=func.__name__, description=func.__doc__, func=func))
            
            logger.info(f"Loaded {len(self.plugin_tools)} plugin tools")
            
        except Exception as err:
            logger.error(f"Failed to initialize plugin tools: {err}")
            self.plugin_tools = []

    async def call_tools_messages(self, messages: List[BaseMessage]) -> AIMessage:
        """Tool selection - sub-agent responsible for tool calling decision"""

        select_tool_message = EventTitleType.SELECT_TOOL if self.step_counter == 1 else EventTitleType.CONTINUE_SELECT_TOOL
        # Send tool analysis start event to main agent
        await self.event_manager.emit_progress(
            select_tool_message,
            EventMessageType.ANALYZING_TOOLS,
            EventStatusType.START,
            EventAgentType.STREAM_AGENT
        )

        call_tool_messages: List[BaseMessage] = []
        # Only initialize when calling tools for the first time
        if self.step_counter == 1:
            tools_schema = []
            for tool in self.tools:
                if isinstance(tool, BaseTool) and tool.args_schema:  # MCP Tool
                    tools_schema.append(mcp_tool_to_args_schema(tool.name, tool.description, tool.args_schema))
                else:
                    if hasattr(tool, "coroutine") and tool.coroutine is not None:
                        tools_schema.append(function_to_args_schema(tool.coroutine))
                    else:
                        tools_schema.append(function_to_args_schema(tool.func))

            self.tool_invocation_model.bind_tools(tools_schema)

        system_message = SystemMessage(content=DEFAULT_CALL_PROMPT)
        call_tool_messages.append(system_message)
        call_tool_messages.extend(messages)

        response = await self.tool_invocation_model.ainvoke(call_tool_messages)
        # Determine if there are tools available for calling
        if response.tool_calls:
            openai_tool_calls = response.tool_calls

            response.tool_calls = convert_langchain_tool_calls(response.tool_calls)

            tool_call_names = [tool_call["name"] for tool_call in response.tool_calls]
            # Send tool selection completion event to main agent
            await self.event_manager.emit_progress(
                select_tool_message,
                EventMessageType.AVAILABLE_TOOLS.format(tool_name=", ".join(set(tool_call_names))),
                EventStatusType.END,
                EventAgentType.STREAM_AGENT
            )

            return AIMessage(
                content=response.content,
                tool_calls=response.tool_calls,
            )
        else:
            # Send no tools available event to main agent
            await self.event_manager.emit_progress(
                select_tool_message,
                EventMessageType.NO_AVAILABLE_TOOL,
                EventStatusType.END,
                EventAgentType.STREAM_AGENT
            )
            return AIMessage(content="No available tools found")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """Tool execution - sub-agent responsible for specific tool execution"""
        tool_calls = messages[-1].tool_calls
        tool_messages: List[BaseMessage] = []

        # Ensure no race conditions occur
        async with self.step_counter_lock:
            self.step_counter += 1

        for tool_call in tool_calls:

            is_mcp_tool, use_tool = self.find_tool_use(tool_call["name"])
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]

            if is_mcp_tool:
                try:
                    personal_config = self.get_mcp_config_by_tool(tool_name)
                    if personal_config:
                        tool_args.update(personal_config)

                    # Send MCP tool invocation event to main agent
                    await self.event_manager.emit_progress(
                        EventTitleType.EXECUTE_MCP_TOOL.format(tool_name=tool_name),
                        EventMessageType.CALL_MCP_TOOL.format(tool_name=tool_name),
                        EventStatusType.START,
                        EventAgentType.STREAM_AGENT
                    )

                    # Call MCP tool to return all results, but currently only handle text data
                    text_content, no_text_content = await use_tool.coroutine(**tool_args)

                    # Send MCP tool execution completion event to main agent
                    await self.event_manager.emit_progress(
                        EventTitleType.EXECUTE_MCP_TOOL.format(tool_name=tool_name),
                        text_content,
                        EventStatusType.END,
                        EventAgentType.STREAM_AGENT
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
            else:

                try:
                    # Add suffix to ensure event messages don't get stuck
                    suffix = " " * self.tool_call_count.get(tool_name, 0)
                    self.tool_call_count[tool_name] = self.tool_call_count.get(tool_name, 0) + 1

                    # Send plugin tool invocation event to main agent
                    await self.event_manager.emit_progress(
                        EventTitleType.EXECUTE_PLUGIN_TOOL.format(tool_name=tool_name),
                        EventMessageType.CALL_PLUGIN_TOOL.format(tool_name=tool_name),
                        EventStatusType.START,
                        EventAgentType.STREAM_AGENT
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
                        EventAgentType.STREAM_AGENT
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


    async def set_agent_graph(self):
        """Set up sub-agent's tool execution graph"""

        # Build tool calling Graph
        async def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]

            # If tool recursive calls exceed 5 times, return END directly
            if self.step_counter > 5:
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

    async def ainvoke(self, messages: List[BaseMessage]):
        """Sub-agent tool execution - only return tool execution results, no model reply"""
        if not self._initialized:
            await self.init_stream_agent()
            
        # Send sub-agent start working event
        await self.event_manager.emit_progress(
            EventTitleType.STREAM_AGENT_START,
            EventMessageType.STARTING_TOOL_EXECUTION,
            EventStatusType.START,
            EventAgentType.STREAM_AGENT
        )
        
        try:
            graph_task = None
            if self.tools and len(self.tools) != 0:
                graph_task = asyncio.create_task(self.graph.ainvoke({"messages": messages}))

            # Wait for tool execution to complete
            if graph_task:
                results = await graph_task
                messages = results["messages"][:-1]  # Remove messages that didn't hit tools
                
                # Send sub-agent work completion event
                tool_count = len([msg for msg in messages if isinstance(msg, ToolMessage)])
                await self.event_manager.emit_progress(
                    EventTitleType.STREAM_AGENT_START,
                    EventMessageType.TOOL_EXECUTION_COMPLETED.format(tool_count=tool_count),
                    EventStatusType.END,
                    EventAgentType.STREAM_AGENT
                )

                messages = [msg for msg in messages if isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage) and msg.tool_calls)]

                return messages
            else:
                # Send no tool execution event
                await self.event_manager.emit_progress(
                    EventTitleType.STREAM_AGENT_START,
                    EventMessageType.NO_TOOLS_NEEDED,
                    EventStatusType.END,
                    EventAgentType.STREAM_AGENT
                )
                return []
                
        except Exception as err:
            logger.error(f"Stream Agent execution failed: {err}")
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": EventTitleType.STREAM_AGENT_START,
                        "message": EventMessageType.EXECUTION_FAILED.format(err=str(err)),
                        "status": EventStatusType.ERROR
                    }
                )
            )
            return []

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
            if tool_name in tools:
                for config in self.mcp_configs:
                    if server_name == config.server_name:
                        return config.personal_config or {}
        return {}
