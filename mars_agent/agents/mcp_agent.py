import asyncio
import inspect
import json
import time
import logging
from typing import List, Dict, Any

from mars_agent.core.langchain.messages import ToolMessage, BaseMessage, AIMessage, SystemMessage, ToolCall, HumanMessage
from mars_agent.core.langchain.tools import BaseTool
from mars_agent.core.langgraph.constants import START, END
from mars_agent.core.langgraph.graph import StateGraph, MessagesState

from mars_agent.core.models.manager import MarsModelManager
from mars_agent.prompts.chat_prompt import DEFAULT_CALL_PROMPT
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.core.models.base_model import BaseMarsModel, MarsModelConfig
from mars_agent.schema import MCPConfig
from mars_agent.utils.util import mcp_tool_to_args_schema, convert_langchain_tool_calls

logger = logging.getLogger(__name__)

class MCPAgent:
    def __init__(self,
                 mcp_config: MCPConfig,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 event_queue: asyncio.Queue = None):
        self.mcp_config = mcp_config
        self.mcp_manager = MCPManager()
        self.event_queue = event_queue

        self.mcp_tools: List[BaseTool] = []
        self.conversation_model = MarsModelManager.get_conversation_model(model_config)
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.graph = None
        self.step_counter = 0
        self.step_counter_lock = asyncio.Lock()

    async def emit_event(self, data: Dict[Any, Any]):
        """发送流式事件"""
        event = {
            "type": "event",
            "timestamp": time.time(),
            "data": data
        }
        await self.event_queue.put(event)

    async def init_mcp_agent(self):
        if self.mcp_config:
            await self.connect_mcp_server()
            self.mcp_tools = await self.set_mcp_tools()

        await self.set_agent_graph()

    async def set_mcp_tools(self):
        mcp_tools = await self.mcp_manager.get_mcp_tools()
        return mcp_tools

    async def connect_mcp_server(self):
        server_info = {
            "url": self.mcp_config.url,
            "type": self.mcp_config.type,
            "server_name": self.mcp_config.server_name
        }
        await self.mcp_manager.connect_mcp_servers([server_info])

    async def call_tools_messages(self, messages: List[BaseMessage]) -> AIMessage:
        """调用工具选择，添加流式事件"""
        select_tool_message = "开始选择可用工具" if self.step_counter == 1 else f"是否需要继续调用工具{' ' * self.step_counter}"

        call_tool_messages: List[BaseMessage] = []

        await self.emit_event({
            "title": select_tool_message,
            "status": "START",
            "message": f"正在分析{self.mcp_config.server_name}下需要使用的工具...",
        })

        # 只有第一次调用工具的时候才会初始化
        if self.step_counter == 0:
            tools_schema = []
            for tool in self.mcp_tools:
                tools_schema.append(mcp_tool_to_args_schema(tool.name, tool.description, tool.args_schema))

            self.tool_invocation_model.bind_tools(tools_schema)

            system_message = SystemMessage(content=DEFAULT_CALL_PROMPT)
            # MCP Agent 单独的Prompt，不受历史记录影响
            call_tool_messages.append(system_message)
            call_tool_messages.append(messages[-1])
        else:
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
                "message": f"{self.mcp_config.server_name}下可用工具：" + ", ".join(set(tool_call_names))
            })

            return AIMessage(
                content="命中可用工具",
                tool_calls=response.tool_calls,
            )
        else:
            # 发送无工具可用事件
            return AIMessage(content="没有命中可用的工具")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """执行工具，添加流式事件"""
        tool_calls = messages[-1].tool_calls
        tool_messages: List[BaseMessage] = []

        for tool_call in tool_calls:
            # 保证不出现竞争条件
            async with self.step_counter_lock:
                self.step_counter += 1

            mcp_tool = self.find_mcp_tool(tool_call["name"])
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_call_id = tool_call["id"]
            try:
                # 针对鉴权的MCP Server需要用户的单独配置，例如飞书、邮箱
                tool_args.update(self.mcp_config.user_config)

                await self.emit_event({
                    "status": "START",
                    "title": f"Run MCP Tool: {tool_name}",
                    "message": f"正在调用MCP工具 {tool_name}..."
                })

                # 调用MCP 工具返回结果
                tool_result = await mcp_tool.coroutine(**tool_args)

                await self.emit_event({
                    "status": "END",
                    "title": f"Run MCP Tool: {tool_name}",
                    "message": tool_result,
                })

                tool_messages.append(
                    ToolMessage(content=tool_result, name=tool_name, tool_call_id=tool_call_id))
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
                    ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages

    async def set_agent_graph(self):
        """设置Agent图，添加流式事件支持"""

        # 构建调用工具Graph
        async def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]

            # 如果工具递归调用次数超过5次，直接返回END
            if self.step_counter > self.mcp_config.max_step:
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

    async def ainvoke(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """非流式版本"""
        result = await self.graph.ainvoke({"messages": messages})
        messages = []
        for message in result["messages"][:-1]: # 去除没有命中工具的AIMessage
            if not isinstance(message, HumanMessage) and not isinstance(message, SystemMessage):
                messages.append(message)
        return messages
        # 是否需要模型总结信息（增加10-20s的时间） ↓
        # return await self.conversation_model.ainvoke(result["messages"][:-1])

    def find_mcp_tool(self, name) -> BaseTool | None:
        for tool in self.mcp_tools:
            if tool.name == name:
                return tool
        return None




