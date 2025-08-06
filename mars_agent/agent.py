import asyncio
import time
import logging
from typing import List, Callable, Union, Any, Dict
from collections.abc import Awaitable
from uuid import uuid4
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage

from mars_agent.schema import MarsModelConfig
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.agents.mcp_agent import MCPAgent
from mars_agent.agents.stream_agent import StreamingAgent
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)


class MarsAgent:
    """
    Mars 主代理 - 负责统一事件管理和模型回复
    
    架构设计:
    - 主代理: 负责事件处理、模型调用、流式响应、资源管理
    - 副代理: StreamingAgent, MCPAgent 负责工具执行，事件上报给主代理
    """
    
    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 mars_agent_id: str = None,
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 memory_path: str = None,
                 mcp_as_agent: bool = True,
                 enable_memory: bool = False,
                 enable_mcp_concurrency: bool = True,
                 mcp_configs: List[MCPBaseConfig] = []):

        self.mcp_agents: List[MCPAgent] = []
        self.mcp_configs = mcp_configs

        # 当Tool Call 模型没有被设置时，让Tool Call模型与Conversation 模型保持一致
        if not tool_call_model_config:
            self.tool_call_model_config = model_config
        else:
            self.tool_call_model_config = tool_call_model_config

        self.model_config = model_config

        self.enable_mcp_concurrency = enable_mcp_concurrency
        self.mcp_as_agent = mcp_as_agent
        self.enable_memory = enable_memory
        self.functions = functions
        self._mars_agent_id = mars_agent_id if mars_agent_id else uuid4().hex

        # 主代理的事件队列和事件管理器 - 统一处理所有事件
        self.event_queue = asyncio.Queue()
        self.event_manager = EventManager(self.event_queue)
        
        # 初始化状态管理
        self._initialized = False
        self.stream_agent = None
        self.conversation_model = None

        self.init_mars_agent()


    async def emit_event(self, data: Dict[Any, Any]):
        """主代理的事件发送方法 - 统一事件格式"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )


    def init_mars_agent(self):
        """初始化主代理和所有副代理 - 带资源管理"""
        try:
            if self._initialized:
                logger.info("Mars Agent already initialized")
                return
                
            if self.mcp_as_agent:
                self.init_mcp_agents()
                self.init_stream_agent()
            else:
                self.init_stream_agent()

            if isinstance(self.model_config, dict):
                self.model_config = MarsModelConfig(**self.model_config)
            if isinstance(self.tool_call_model_config, dict):
                self.tool_call_model_config = MarsModelConfig(**self.tool_call_model_config)

            # 主代理负责模型调用
            self.conversation_model = MarsModelManager.get_conversation_model(self.model_config)
            
            self._initialized = True
            logger.info("Mars Agent initialized successfully")
            
        except Exception as err:
            logger.error(f"Failed to initialize Mars Agent: {err}")
            raise

    def init_mcp_agents(self):
        """初始化MCP副代理，传入主代理的事件队列"""
        self.mcp_agents = []
        for mcp_config in self.mcp_configs:
            # 将主代理的事件队列传给副代理，实现事件统一管理
            mcp_agent = MCPAgent(mcp_config,
                                 self.model_config,
                                 self.tool_call_model_config,
                                 self.event_queue)  # 副代理使用主代理的事件队列
            self.mcp_agents.append(mcp_agent)

    # # 新增：在主代理的生命周期内统一初始化所有MCP连接
    # async def init_mcp_connections(self):
    #     """为所有MCP副代理初始化连接"""
    #     if self.enable_mcp_concurrency:
    #         init_tasks = [agent.init_mcp_agent() for agent in self.mcp_agents]
    #         results = await asyncio.gather(*init_tasks, return_exceptions=True)
    #         for result in results:
    #             if isinstance(result, Exception):
    #                 logger.error(f"Failed to initialize an MCP agent: {result}")
    #     else:
    #         for agent in self.mcp_agents:
    #             try:
    #                 await agent.init_mcp_agent()
    #             except Exception as e:
    #                 logger.error(f"Failed to initialize an MCP agent: {e}")

    def init_stream_agent(self):
        """初始化Stream副代理，传入主代理的事件队列"""
        try:
            if self.mcp_as_agent:
                self.stream_agent = StreamingAgent(self.model_config,
                                                   self.tool_call_model_config,
                                                   functions=self.functions,
                                                   event_queue=self.event_queue)  # 副代理使用主代理的事件队列
            else:
                self.stream_agent = StreamingAgent(self.model_config,
                                                   self.tool_call_model_config,
                                                   functions=self.functions,
                                                   mcp_configs=self.mcp_configs,
                                                   event_queue=self.event_queue)  # 副代理使用主代理的事件队列
            
        except Exception as err:
            logger.error(f"Failed to initialize Stream Agent: {err}")
            raise

    @property
    def mars_agent_id(self):
        return self._mars_agent_id

    async def call_mcp_agent_messages(self, messages: List[BaseMessage]):
        """调用MCP副代理执行工具，事件自动上报到主代理"""

        async def process_mcp_agent(mcp_agent: MCPAgent):
            # MCP副代理执行工具，事件自动发送到主代理事件队列
            try:
                # 修复：移除此处的初始化调用，连接已在主代理中统一管理
                responses = await mcp_agent.ainvoke(messages)
                return responses
            except Exception as err:
                logger.error(f"MCP Agent {mcp_agent.mcp_config.server_name} failed: {err}")
                return []

        if self.enable_mcp_concurrency:
            process_tasks = [process_mcp_agent(mcp_agent) for mcp_agent in self.mcp_agents]
            results = await asyncio.gather(*process_tasks, return_exceptions=True)
        else:
            results = []
            for mcp_agent in self.mcp_agents:
                result = await process_mcp_agent(mcp_agent)
                results.append(result)

        # 获取MCP Agent信息并返回
        mcp_agent_messages: List[BaseMessage] = []
        for result in results:
            if isinstance(result, list):
                mcp_agent_messages.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"MCP Agent execution failed: {result}")
        return mcp_agent_messages

    async def call_stream_agent_messages(self, messages: List[BaseMessage]):
        """调用Stream副代理执行工具，事件自动上报到主代理"""
        if self.functions and self.stream_agent:
            try:
                # Stream副代理执行工具，事件自动发送到主代理事件队列
                return await self.stream_agent.ainvoke(messages)
            except Exception as err:
                logger.error(f"Stream Agent execution failed: {err}")
                return []
        return []

    async def ainvoke(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
        """主代理的非流式调用 - 统一处理副代理结果和模型回复"""
        if not self._initialized:
            self.init_mars_agent()
            
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        # 并行调用副代理
        stream_agent_task = None
        if self.functions:
            stream_agent_task = asyncio.create_task(self.call_stream_agent_messages(messages.copy()))

        mcp_agent_task = None
        if self.mcp_configs and self.mcp_as_agent:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # 等待副代理完成
        if stream_agent_task:
            stream_agent_messages = await stream_agent_task
        else:
            stream_agent_messages = None

        if mcp_agent_task:
            mcp_agent_messages = await mcp_agent_task
        else:
            mcp_agent_messages = None

        # 合并副代理的结果
        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)

        # 主代理负责最终的模型调用
        try:
            response = await self.conversation_model.ainvoke(messages)
            return response
        except Exception as err:
            logger.error(f"Main agent model invocation failed: {err}")
            raise


    async def astream(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
        """主代理的流式调用 - 统一处理事件流和模型回复"""
        # if not self._initialized:
        #     await self.init_mars_agent()
            
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        # 并行启动副代理任务
        stream_agent_task = None
        if self.functions:
            stream_agent_task = asyncio.create_task(self.call_stream_agent_messages(messages.copy()))

        mcp_agent_task = None
        if self.mcp_configs and self.mcp_as_agent:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # 收集所有副代理任务
        all_tasks = [task for task in [stream_agent_task, mcp_agent_task] if task is not None]

        # 主代理统一处理事件流 - 接收来自副代理的所有事件
        async for event in self.event_manager.stream_with_heartbeat(all_tasks):
            yield event

        # 等待副代理完成并收集结果
        stream_agent_messages = stream_agent_task.result() if stream_agent_task and stream_agent_task.done() else None
        mcp_agent_messages = mcp_agent_task.result() if mcp_agent_task and mcp_agent_task.done() else None

        # 合并副代理的工具执行结果
        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)

        # 主代理负责最终的模型回复流式处理
        response_content = ""
        try:
            # 发送模型回复开始事件
            await self.event_manager.emit_progress(
                "模型回复",
                "正在生成回复...",
                "START"
            )
            
            async for chunk in self.conversation_model.astream(messages):
                if chunk.content:
                    response_content += chunk.content
                    # 主代理统一处理响应块事件
                    yield self.event_manager.create_response_chunk_event(chunk.content, response_content)

            # 发送模型回复完成事件
            await self.event_manager.emit_progress(
                "模型回复",
                "回复生成完成",
                "END"
            )
            
        # 主代理统一处理错误
        except Exception as err:
            logger.error(f"LLM Model Error: {err}")
            # 发送错误事件
            await self.event_manager.emit_event(
                self.event_manager.create_event(
                    EventType.ERROR,
                    {
                        "title": "模型回复错误",
                        "message": str(err),
                        "status": "ERROR"
                    }
                )
            )
            # 发送兜底回复
            yield self.event_manager.create_response_chunk_event(
                "您的问题触及到我的知识盲区，请换个问题吧✨",
                response_content
            )

    def invoke(self):
        """同步调用接口（待实现）"""
        pass

    def stream(self):
        """同步流式接口（待实现）"""
        pass


if __name__ == "__main__":
    pass