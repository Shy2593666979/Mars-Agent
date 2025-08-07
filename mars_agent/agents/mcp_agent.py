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
from mars_agent.schema import MarsModelConfig
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.util import mcp_tool_to_args_schema, convert_langchain_tool_calls
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEP = 5

class MCPAgent:
    """
    MCP 副代理 - 负责MCP工具执行
    
    职责:
    - MCP服务器连接和工具调用
    - 事件上报给主代理
    - 不负责模型回复（由主代理处理）
    - 正确的资源生命周期管理
    """
    
    def __init__(self,
                 mcp_config: MCPBaseConfig,
                 model_config: MarsModelConfig,
                 tool_call_model_config: MarsModelConfig,
                 event_queue: asyncio.Queue = None):

        self.mcp_config = mcp_config
        self.mcp_manager = MCPManager([mcp_config])
        self.event_queue = event_queue

        # 使用主代理的事件队列，事件自动上报给主代理
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()

        self.mcp_tools: List[BaseTool] = []
        # 副代理只需要工具调用模型，不需要对话模型
        self.tool_invocation_model = MarsModelManager.get_tool_call_model(tool_call_model_config)
        self.graph = None
        self.step_counter = 0
        self.step_counter_lock = asyncio.Lock()
        self._initialized = False

    async def emit_event(self, data: Dict[Any, Any]):
        """副代理事件发送 - 自动上报给主代理"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )

    async def init_mcp_agent(self):
        """初始化MCP Agent - 带资源管理"""
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
        """获取MCP工具"""
        try:
            mcp_tools = await self.mcp_manager.get_mcp_tools()
            return mcp_tools
        except Exception as err:
            logger.error(f"Failed to get MCP tools: {err}")
            return []

    async def call_tools_messages(self, messages: List[BaseMessage]) -> AIMessage:
        """MCP工具选择 - 副代理负责MCP工具调用决策"""
        select_tool_message = "开始选择可用工具" if self.step_counter == 1 else f"是否需要继续调用工具{' ' * self.step_counter}"

        call_tool_messages: List[BaseMessage] = []

        # 发送MCP工具分析开始事件到主代理
        await self.event_manager.emit_progress(
            select_tool_message,
            f"正在分析{self.mcp_config.server_name}下需要使用的工具...",
            "START",
            agent=f"{self.mcp_config.server_name} | MCP Agent"
        )

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
            # 发送MCP工具选择完成事件到主代理
            await self.event_manager.emit_progress(
                select_tool_message,
                f"{self.mcp_config.server_name}下可用工具：" + ", ".join(set(tool_call_names)),
                "END",
                agent=f"{self.mcp_config.server_name} | MCP Agent"
            )

            return AIMessage(
                content="命中可用工具",
                tool_calls=response.tool_calls,
            )
        else:
            await self.event_manager.emit_progress(
                select_tool_message,
                "没有命中可用的工具",
                "END",
                agent=f"{self.mcp_config.server_name} | MCP Agent"
            )

            # 发送无MCP工具可用事件到主代理
            return AIMessage(content="没有命中可用的工具")

    async def execute_tool_message(self, messages: List[ToolMessage]):
        """MCP工具执行 - 副代理负责具体MCP工具执行"""
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
                if self.mcp_config.personal_config:
                    tool_args.update(self.mcp_config.personal_config)

                # 发送MCP工具执行开始事件到主代理
                await self.event_manager.emit_progress(
                    f"执行MCP可用工具: {tool_name}",
                    f"正在调用MCP工具 {tool_name}...",
                    "START",
                    agent=f"{self.mcp_config.server_name} | MCP Agent"
                )

                # 调用MCP 工具返回全部结果，但是目前仅处理文本数据
                text_content, no_text_content = await mcp_tool.coroutine(**tool_args)

                # 发送MCP工具执行完成事件到主代理
                await self.event_manager.emit_progress(
                    f"执行MCP可用工具: {tool_name}",
                    text_content,
                    "END",
                    agent=f"{self.mcp_config.server_name} | MCP Agent"
                )

                tool_messages.append(
                    ToolMessage(content=text_content, name=tool_name, tool_call_id=tool_call_id))
                logger.info(f"MCP Tool {tool_name}, Args: {tool_args}, Result: {text_content}")

            except Exception as err:
                # 发送MCP工具执行错误事件到主代理
                await self.event_manager.emit_event(
                    self.event_manager.create_event(
                        EventType.ERROR,
                        {
                            "title": f"执行MCP可用工具: {tool_name}",
                            "message": str(err),
                            "status": "ERROR"
                        }
                    )
                )

                logger.error(f"MCP Tool {tool_name} Error: {str(err)}")
                tool_messages.append(
                    ToolMessage(content=str(err), name=tool_name, tool_call_id=tool_call_id))

        return tool_messages

    async def set_agent_graph(self):
        """设置MCP Agent的工具执行图"""

        # 构建调用工具Graph
        async def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]

            # 如果工具递归调用次数超过DEFAULT_MAX_STEP次，直接返回END
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

        # 设置起始节点
        workflow.add_edge(START, "call_tool_node")
        # 设置判断是否调用工具边
        workflow.add_conditional_edges("call_tool_node", should_continue)
        # 检测是否存在工具递归信息
        workflow.add_edge("execute_tool_node", "call_tool_node")

        self.graph = workflow.compile()

    async def ainvoke(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """MCP Agent的工具执行 - 只返回MCP工具执行结果，不进行模型回复"""
        if not self._initialized:
            await self.init_mcp_agent()

        # 发送MCP Agent开始工作事件
        await self.event_manager.emit_progress(
            f"{self.mcp_config.server_name} | MCP Agent",
            "开始执行MCP工具调用...",
            "START",
            agent=f"{self.mcp_config.server_name} | MCP Agent"
        )
        
        try:
            result = await self.graph.ainvoke({"messages": messages})
            messages = []
            for message in result["messages"][:-1]: # 去除没有命中工具的AIMessage
                if not isinstance(message, HumanMessage) and not isinstance(message, SystemMessage):
                    messages.append(message)
            
            # 发送MCP Agent完成工作事件
            tool_count = len([msg for msg in messages if isinstance(msg, ToolMessage)])
            await self.event_manager.emit_progress(
                f"{self.mcp_config.server_name} | MCP Agent",
                f"MCP工具执行完成，共执行{tool_count}个工具" if tool_count > 0 else "无MCP工具需要执行",
                "END",
                agent=f"{self.mcp_config.server_name} | MCP Agent"
            )
            
            return messages
            
        except Exception as err:
            logger.error(f"MCP Agent {self.mcp_config.server_name} execution failed: {err}")
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": f"{self.mcp_config.server_name} | MCP Agent",
                        "message": f"执行失败: {str(err)}",
                        "status": "ERROR"
                    }
                )
            )
            return []

    def find_mcp_tool(self, name) -> BaseTool | None:
        """根据名称查找MCP工具"""
        for tool in self.mcp_tools:
            if tool.name == name:
                return tool
        return None





