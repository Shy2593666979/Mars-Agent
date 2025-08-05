import asyncio
import copy
import json
import time
import inspect
import logging
from typing import List, Dict, Any, AsyncGenerator
from mars_agent.core.langchain.messages import BaseMessage, AIMessage, SystemMessage, ToolMessage, HumanMessage, ToolCall
from mars_agent.core.langchain.tools import BaseTool, Tool
from mars_agent.core.langgraph.graph import MessagesState, StateGraph, END, START

from mars_agent.core.models.base_model import BaseMarsModel, MarsModelConfig
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.prompts.chat_prompt import DEFAULT_CALL_PROMPT
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.schema import MCPConfig
from mars_agent.utils.util import convert_langchain_tool_calls, function_to_args_schema, mcp_tool_to_args_schema

logger = logging.getLogger(__name__)

class StreamingAgent:
    def __init__(self,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 mcp_configs: List[MCPConfig] = [],
                 functions: List = []):

        self.conversation_model = MarsModelManager.get_conversation_model(model_config)
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.plugin_tools = []
        self.mcp_tools = []
        self.graph = None
        self.mcp_configs = mcp_configs
        self.tools = []
        self.mcp_manager = MCPManager()
        self.functions = functions

        # 流式事件队列
        self.event_queue = asyncio.Queue()
        self.step_counter_lock = asyncio.Lock()
        self.step_counter = 1

        # 记录工具调用次数
        self.tool_call_count: dict[str, int] = {}

        # 根据server name找user config
        self.server_dict: dict[str, Any] = {}


    async def emit_event(self, data: Dict[Any, Any]):
        """发送流式事件"""
        event = {
            "type": "event",
            "timestamp": time.time(),
            "data": data
        }
        await self.event_queue.put(event)

    async def init_agent(self):
        await self.set_agent_graph()
        await self.init_mcp_tools()
        await self.init_plugin_tools()

        self.tools = self.plugin_tools + self.mcp_tools

    async def init_mcp_tools(self):
        # 与MCP Server建立链接
        servers_info = []
        for mcp_config in self.mcp_configs:
            servers_info.append({
                "url": mcp_config.url,
                "type": mcp_config.type,
                "server_name": mcp_config.server_name
            })
        await self.mcp_manager.connect_mcp_servers(servers_info)

        self.mcp_tools = await self.mcp_manager.get_mcp_tools()

        mcp_servers_info = await self.mcp_manager.show_mcp_tools()
        self.server_dict = {server_name: [tool.name for tool in tools_info] for server_name, tools_info in mcp_servers_info.items()}

    async def init_plugin_tools(self):
        self.plugin_tools = []

        # 无意义函数，但是Tool需要一个func
        def _t():
            pass

        for func in self.functions:
            if asyncio.iscoroutine(func):
                self.plugin_tools.append(Tool(name=func.__name__, description=func.__doc__, func=_t, coroutine=func))
            else:
                self.plugin_tools.append(Tool(name=func.__name__, description=func.__doc__, func=func))



    async def call_tools_messages(self, messages: List[BaseMessage]) -> AIMessage:
        """调用工具选择，添加流式事件"""

        select_tool_message = "开始选择可用工具" if self.step_counter == 1 else f"是否需要继续调用工具{' ' * self.step_counter}"
        # 发送工具分析开始事件
        await self.emit_event({
            "title": select_tool_message,
            "status": "START",
            "message": "正在分析需要使用的工具...",
        })

        call_tool_messages: List[BaseMessage] = []
        # 只有第一次调用工具的时候才会初始化
        if self.step_counter == 1:
            tools_schema = []
            for tool in self.tools:
                if isinstance(tool, BaseTool) and tool.args_schema:  # MCP Tool
                    tools_schema.append(mcp_tool_to_args_schema(tool.name, tool.description, tool.args_schema))
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
            # 发送工具选择完成事件
            await self.emit_event({
                "title": select_tool_message,
                "status": "END",
                "message": "可用工具：" + ", ".join(set(tool_call_names))
            })

            return AIMessage(
                content=response.content,
                tool_calls=response.tool_calls,
            )
        else:
            # 发送无工具可用事件
            await self.emit_event({
                "title": select_tool_message,
                "status": "END",
                "message": "没有命中可用的工具"
            })
            return AIMessage(content="没有命中可用的工具")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """执行工具，添加流式事件"""
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
                    mcp_config = self.get_mcp_config_by_tool(tool_name)

                    tool_args.update(mcp_config)

                    # 发送MCP工具调用事件
                    await self.emit_event({
                        "status": "START",
                        "title": f"Run MCP Tool: {tool_name}",
                        "message": f"正在调用MCP工具 {tool_name}..."
                    })

                    # 调用MCP 工具返回结果
                    tool_result = await use_tool.coroutine(**tool_args)

                    # 发送MCP工具执行完成事件
                    await self.emit_event({
                        "status": "END",
                        "title": f"Run MCP Tool: {tool_name}",
                        "message": tool_result,
                    })

                    tool_messages.append(
                        ToolMessage(content=tool_result, name=tool_name + "_mcp", tool_call_id=tool_call_id))
                    logger.info(f"MCP Tool {tool_name}, Args: {tool_args}, Result: {tool_result}")

                except Exception as err:
                    # 发送MCP工具执行错误事件
                    await self.emit_event({
                        "status": "ERROR",
                        "message": str(err),
                        "title": f"Run MCP Tool: {tool_name}",
                    })

                    logger.error(f"MCP Tool {tool_name} Error: {str(err)}")
                    tool_messages.append(
                        ToolMessage(content=str(err), name=tool_name + "_mcp", tool_call_id=tool_call_id))
            else:

                try:
                    # 给加个后缀保证事件消息不卡掉
                    suffix = " " * self.tool_call_count.get(tool_name, 0)
                    self.tool_call_count[tool_name] = self.tool_call_count.get(tool_name, 0) + 1

                    # 发送插件工具调用事件
                    await self.emit_event({
                        "status": "START",
                        "title": f"执行可用工具: {tool_name}{suffix}",
                        "message": f"正在调用插件工具 {tool_name}..."
                    })

                    if use_tool.coroutine:
                        tool_result = await use_tool.coroutine(**tool_args)
                    else:
                        # 改为异步
                        tool_result = await asyncio.to_thread(use_tool.func, **tool_args)

                    # 发送插件工具执行完成事件
                    await self.emit_event({
                        "status": "END",
                        "title": f"执行可用工具: {tool_name}{suffix}",
                        "message": tool_result,
                    })

                    tool_messages.append(
                        ToolMessage(content=tool_result, name=tool_name, tool_call_id=tool_call_id))
                    logger.info(f"Plugin Tool {tool_name}, Args: {tool_args}, Result: {tool_result}")

                except Exception as err:
                    # 发送插件工具执行错误事件
                    await self.emit_event({
                        "status": "ERROR",
                        "title": f"执行可用工具: {tool_name}{suffix}",
                        "message": str(err),
                    })

                    logger.error(f"Plugin Tool {tool_name} Error: {str(err)}")
                    tool_messages.append(
                        ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages


    async def set_agent_graph(self):
        """设置Agent图，添加流式事件支持"""

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

    async def ainvoke_streaming(self, messages: List[BaseMessage]) -> AsyncGenerator[Dict[str, Any], None]:
        """流式调用主方法"""

        # 启动图执行
        graph_task = None
        if self.tools and len(self.tools) != 0:
            graph_task = asyncio.create_task(self.graph.ainvoke({"messages": messages}))

        # 收集所有任务
        all_tasks = [task for task in [graph_task] if task is not None]

        # 流式返回事件
        conversation_ended = False

        while not conversation_ended:
            try:
                # 等待事件或超时
                event = await asyncio.wait_for(self.event_queue.get(), timeout=5.0)
                yield event

            except asyncio.TimeoutError:
                # 发送心跳事件
                yield {
                    "type": "heartbeat",
                    "timestamp": time.time(),
                    "data": {"message": "连接保持中..."}
                }

            # 检查任务执行是否完成
            if all(task.done() for task in all_tasks):
                conversation_ended = True


        # 等待图执行完成
        if graph_task and graph_task.done():
            results = graph_task.result()
            messages = results["messages"][:-1]  # 去除没有命中工具的message

        response_content = ""
        try:
            async for chunk in self.conversation_model.astream(messages):
                response_content += chunk.content
                yield {
                    "type": "response_chunk",
                    "timestamp": time.time(),
                    "data": {
                        "chunk": chunk.content,
                        "accumulated": response_content
                    }
                }
        # 针对模型回复进行兜底操作，错误类型包括：敏感词，模型问题
        except Exception as err:
            logger.error(f"LLM Model Error: {err}")
            yield {
                "type": "response_chunk",
                "timestamp": time.time(),
                "data": {
                    "chunk": "您的问题触及到我的知识盲区，请换个问题吧✨",
                    "accumulated": response_content
                }
            }

    # 非流式版本（保持向后兼容）
    async def ainvoke(self, messages: List[BaseMessage], event_queue):
        """非流式版本（保持向后兼容）"""
        self.event_queue = event_queue
        graph_task = None
        if self.tools and len(self.tools) != 0:
            graph_task = asyncio.create_task(self.graph.ainvoke({"messages": messages}))

        # 等待所有任务完成
        if graph_task:
            results = await graph_task
            messages = results["messages"][:-1]  # 去除没有命中工具的message
        else:
            messages = messages.copy()

        return messages
        # # 收集完整响应
        # response_content = ""
        # async for chunk in self.conversation_model.astream(messages):
        #     response_content += chunk.content
        #
        # return response_content

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
                        return config.user_config
        return {}