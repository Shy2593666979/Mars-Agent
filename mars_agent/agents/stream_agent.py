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

from mars_agent.schema import MarsModelConfig
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.prompts.chat_prompt import DEFAULT_CALL_PROMPT
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.util import convert_langchain_tool_calls, function_to_args_schema, mcp_tool_to_args_schema
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)

class StreamingAgent:
    """
    Stream 副代理 - 负责插件和MCP工具执行
    
    职责:
    - 工具调用和执行
    - 事件上报给主代理
    - 不负责模型回复（由主代理处理）
    - 正确的资源生命周期管理
    """
    
    def __init__(self,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 mcp_configs: List[MCPBaseConfig] = [],
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 event_queue: asyncio.Queue = None):

        # 副代理只需要工具调用模型，不需要对话模型
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.plugin_tools = []
        self.mcp_tools = []
        self.graph = None
        self.mcp_configs = mcp_configs
        self.tools = []
        self.mcp_manager = MCPManager(mcp_configs)
        self.functions = functions

        # 使用主代理的事件队列，事件自动上报给主代理
        self.event_queue = event_queue
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()
        self.step_counter_lock = asyncio.Lock()
        self.step_counter = 1

        # 记录工具调用次数
        self.tool_call_count: dict[str, int] = {}

        # 根据server name找user config
        self.server_dict: dict[str, Any] = {}
        
        # 初始化状态管理
        self._initialized = False


    async def emit_event(self, data: Dict[Any, Any]):
        """副代理事件发送 - 自动上报给主代理"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )

    async def init_stream_agent(self):
        """初始化副代理 - 带资源管理"""
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
        """初始化MCP工具 - 带错误处理"""
        if not self.mcp_configs:
            self.mcp_tools = []
            return
            
        try:
            # 与MCP Server建立链接
            self.mcp_tools = await self.mcp_manager.get_mcp_tools()

            mcp_servers_info = await self.mcp_manager.show_mcp_tools()
            self.server_dict = {server_name: [tool["name"] for tool in tools_info] for server_name, tools_info in mcp_servers_info.items()}

            logger.info(f"Loaded {len(self.mcp_tools)} MCP tools from MCP servers")
                
        except Exception as err:
            logger.error(f"Failed to initialize MCP tools: {err}")
            self.mcp_tools = []

    async def init_plugin_tools(self):
        """初始化插件工具 - 带错误处理"""
        self.plugin_tools = []

        # 无意义函数，但是Tool需要一个func
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
        """工具选择 - 副代理负责工具调用决策"""

        select_tool_message = "开始选择可用工具" if self.step_counter == 1 else f"是否需要继续调用工具{' ' * self.step_counter}"
        # 发送工具分析开始事件到主代理
        await self.event_manager.emit_progress(
            select_tool_message,
            "正在分析需要使用的工具...",
            "START"
        )

        call_tool_messages: List[BaseMessage] = []
        # 只有第一次调用工具的时候才会初始化
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
        # 判断是否有工具可调用
        if response.tool_calls:
            openai_tool_calls = response.tool_calls

            response.tool_calls = convert_langchain_tool_calls(response.tool_calls)

            tool_call_names = [tool_call["name"] for tool_call in response.tool_calls]
            # 发送工具选择完成事件到主代理
            await self.event_manager.emit_progress(
                select_tool_message,
                "可用工具：" + ", ".join(set(tool_call_names)),
                "END"
            )

            return AIMessage(
                content=response.content,
                tool_calls=response.tool_calls,
            )
        else:
            # 发送无工具可用事件到主代理
            await self.event_manager.emit_progress(
                select_tool_message,
                "没有命中可用的工具",
                "END"
            )
            return AIMessage(content="没有命中可用的工具")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """工具执行 - 副代理负责具体工具执行"""
        tool_calls = messages[-1].tool_calls
        tool_messages: List[BaseMessage] = []

        # 保证不出现竞争条件
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

                    # 发送MCP工具调用事件到主代理
                    await self.event_manager.emit_progress(
                        f"Run MCP Tool: {tool_name}",
                        f"正在调用MCP工具 {tool_name}...",
                        "START"
                    )

                    # 调用MCP 工具返回结果
                    tool_result = await use_tool.coroutine(**tool_args)

                    # 发送MCP工具执行完成事件到主代理
                    await self.event_manager.emit_progress(
                        f"Run MCP Tool: {tool_name}",
                        tool_result,
                        "END"
                    )

                    tool_messages.append(
                        ToolMessage(content=tool_result, name=tool_name + "_mcp", tool_call_id=tool_call_id))
                    logger.info(f"MCP Tool {tool_name}, Args: {tool_args}, Result: {tool_result}")

                except Exception as err:
                    # 发送MCP工具执行错误事件到主代理
                    await self.event_manager.emit_event(
                        self.event_manager.create_event(
                            EventType.ERROR,
                            {
                                "title": f"Run MCP Tool: {tool_name}",
                                "message": str(err),
                                "status": "ERROR"
                            }
                        )
                    )

                    logger.error(f"MCP Tool {tool_name} Error: {str(err)}")
                    tool_messages.append(
                        ToolMessage(content=str(err), name=tool_name + "_mcp", tool_call_id=tool_call_id))
            else:

                try:
                    # 给加个后缀保证事件消息不卡掉
                    suffix = " " * self.tool_call_count.get(tool_name, 0)
                    self.tool_call_count[tool_name] = self.tool_call_count.get(tool_name, 0) + 1

                    # 发送插件工具调用事件到主代理
                    await self.event_manager.emit_progress(
                        f"执行可用工具: {tool_name}{suffix}",
                        f"正在调用插件工具 {tool_name}...",
                        "START"
                    )

                    if hasattr(use_tool, "coroutine") and use_tool.coroutine is not None:
                        tool_result = await use_tool.coroutine(**tool_args)
                    else:
                        # 改为异步
                        tool_result = await asyncio.to_thread(use_tool.func, **tool_args)

                    # 发送插件工具执行完成事件到主代理
                    await self.event_manager.emit_progress(
                        f"执行可用工具: {tool_name}{suffix}",
                        tool_result,
                        "END"
                    )

                    tool_messages.append(
                        ToolMessage(content=tool_result, name=tool_name, tool_call_id=tool_call_id))
                    logger.info(f"Plugin Tool {tool_name}, Args: {tool_args}, Result: {tool_result}")

                except Exception as err:
                    # 发送插件工具执行错误事件到主代理
                    await self.event_manager.emit_event(
                        self.event_manager.create_event(
                            EventType.ERROR,
                            {
                                "title": f"执行可用工具: {tool_name}{suffix}",
                                "message": str(err),
                                "status": "ERROR"
                            }
                        )
                    )

                    logger.error(f"Plugin Tool {tool_name} Error: {str(err)}")
                    tool_messages.append(
                        ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages


    async def set_agent_graph(self):
        """设置副代理的工具执行图"""

        # 构建调用工具Graph
        async def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]

            # 如果工具递归调用次数超过5次，直接返回END
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

        # 设置起始节点
        workflow.add_edge(START, "call_tool_node")
        # 设置判断是否调用工具边
        workflow.add_conditional_edges("call_tool_node", should_continue)
        # 检测是否存在工具递归信息
        workflow.add_edge("execute_tool_node", "call_tool_node")

        self.graph = workflow.compile()

    async def ainvoke(self, messages: List[BaseMessage]):
        """副代理的工具执行 - 只返回工具执行结果，不进行模型回复"""
        if not self._initialized:
            await self.init_stream_agent()
            
        # 发送副代理开始工作事件
        await self.event_manager.emit_progress(
            "Stream Agent",
            "开始执行工具调用...",
            "START"
        )
        
        try:
            graph_task = None
            if self.tools and len(self.tools) != 0:
                graph_task = asyncio.create_task(self.graph.ainvoke({"messages": messages}))

            # 等待工具执行完成
            if graph_task:
                results = await graph_task
                messages = results["messages"][:-1]  # 去除没有命中工具的message
                
                # 发送副代理完成工作事件
                tool_count = len([msg for msg in messages if isinstance(msg, ToolMessage)])
                await self.event_manager.emit_progress(
                    "Stream Agent",
                    f"工具执行完成，共执行{tool_count}个工具",
                    "END"
                )

                messages = [msg for msg in messages if isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage) and msg.tool_calls)]

                return messages
            else:
                # 发送无工具执行事件
                await self.event_manager.emit_progress(
                    "Stream Agent",
                    "无工具需要执行",
                    "END"
                )
                return []
                
        except Exception as err:
            logger.error(f"Stream Agent execution failed: {err}")
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": "Stream Agent",
                        "message": f"执行失败: {str(err)}",
                        "status": "ERROR"
                    }
                )
            )
            return []

    # 新增辅助方法
    def find_tool_use(self, tool_name: str):
        """判断是否为MCP工具并返回对应的工具实例"""
        for tool in self.mcp_tools:
            if tool.name == tool_name:
                return True, tool

        for tool in self.plugin_tools:
            if tool.name == tool_name:
                return False, tool

        raise ValueError(f"系统中不存在该工具: {tool_name}")

    # 获得MCP Server 的 user config
    def get_mcp_config_by_tool(self, tool_name):
        for server_name, tools in self.server_dict.items():
            if tool_name in tools:
                for config in self.mcp_configs:
                    if server_name == config.server_name:
                        return config.personal_config
        return {}
