import asyncio
import time
import logging
from typing import List, Callable, Union, Any, Dict
from collections.abc import Awaitable
from uuid import uuid4
from mars_agent.core.langchain.messages import BaseMessage, ToolMessage, HumanMessage

from mars_agent.core.models.base_model import MarsModelConfig
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.agents.mcp_agent import MCPAgent
from mars_agent.agents.stream_agent import StreamingAgent
from mars_agent.schema import MCPConfig

logger = logging.getLogger(__name__)


class MarsAgent:
    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 mars_agent_id: str = None,
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 memory_path: str = None,
                 mcp_as_agent: bool = True,
                 enable_memory: bool = False,
                 enable_mcp_concurrency: bool = True,
                 mcp_configs: List[MCPConfig] = []):

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


        # 流式事件队列
        self.event_queue = asyncio.Queue()


    async def emit_event(self, data: Dict[Any, Any]):
        """发送流式事件"""
        event = {
            "type": "event",
            "timestamp": time.time(),
            "data": data
        }
        await self.event_queue.put(event)


    async def init_mars_agent(self):
        if self.mcp_as_agent:
            self.init_mcp_agents()
            await self.init_stream_agent()
        else:
            await self.init_stream_agent()

        if isinstance(self.model_config, dict):
            self.model_config = MarsModelConfig(**self.model_config)
        if isinstance(self.tool_call_model_config, dict):
            self.tool_call_model_config = MarsModelConfig(**self.tool_call_model_config)

        self.conversation_model = MarsModelManager.get_conversation_model(self.model_config)

    def init_mcp_agents(self):
        self.mcp_agents = []
        for mcp_config in self.mcp_configs:
            mcp_agent = MCPAgent(mcp_config, self.model_config, self.tool_call_model_config)
            self.mcp_agents.append(mcp_agent)

    async def init_stream_agent(self):
        if self.mcp_as_agent:
            self.stream_agent = StreamingAgent(self.model_config, self.tool_call_model_config, functions=self.functions)
        else:
            self.stream_agent = StreamingAgent(self.model_config, self.tool_call_model_config, functions=self.functions, mcp_configs=self.mcp_configs)
        await self.stream_agent.init_agent()

    @property
    def mars_agent_id(self):
        return self._mars_agent_id

    async def call_mcp_agent_messages(self, messages: List[BaseMessage]):

        async def process_mcp_agent(mcp_agent: MCPAgent):
            # 开始执行MCP Agent
            await self.emit_event({
                "status": "START",
                "title": f"执行 MCP Agent: {mcp_agent.mcp_config.server_name}",
                "message": "开始执行MCP Agent...",
            })

            await mcp_agent.init_mcp_agent()

            responses = await mcp_agent.ainvoke(messages)

            # 返回MCP Agent结果
            await self.emit_event({
                "title": f"执行 MCP Agent: {mcp_agent.mcp_config.server_name}",
                "message": "\n\n".join([response.content for response in responses if isinstance(response, ToolMessage)]) if len(responses) else "该MCP Server下无可用工具",
                "status": "END"
            })
            return responses

        if self.enable_mcp_concurrency:
            process_tasks = [process_mcp_agent(mcp_agent) for mcp_agent in self.mcp_agents]
            results = await asyncio.gather(*process_tasks, return_exceptions=True)
        else:
            results = []
            for mcp_agent in self.mcp_agents:
                await self.emit_event({
                    "status": "START",
                    "title": f"执行 MCP Agent: {mcp_agent.mcp_config.server_name}",
                    "message": "开始执行MCP Agent...",
                })

                await mcp_agent.init_mcp_agent()
                result = await mcp_agent.ainvoke(messages)
                await self.emit_event({
                    "status": "START",
                    "title": f"执行 MCP Agent: {mcp_agent.mcp_config.server_name}",
                    "message": "\n\n".join([res.content for res in result if isinstance(res, ToolMessage)]) if len(result) else "该MCP Server下无可用工具",
                })

                results.append(result)

        # 获取MCP Agent信息并返回
        mcp_agent_messages: List[BaseMessage] = []
        for result in results:
            mcp_agent_messages.extend(result)
        return mcp_agent_messages

    async def ainvoke(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        stream_agent_task = None

        if self.functions:
            stream_agent_task = asyncio.create_task(self.stream_agent.ainvoke(messages.copy()))

        mcp_agent_task = None
        if self.mcp_configs:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # 收集所有任务
        all_tasks = [task for task in [stream_agent_task, mcp_agent_task] if task is not None]

        if stream_agent_task:
            stream_agent_messages = await stream_agent_task
        else:
            stream_agent_messages = None

        if mcp_agent_task:
            mcp_agent_messages = await mcp_agent_task
        else:
            mcp_agent_messages = None

        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)



        response = await self.conversation_model.ainvoke(messages)
        return response


    async def astream(self,messages: Union[str, BaseMessage, List[BaseMessage]]):
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        stream_agent_task = None

        if self.functions:
            stream_agent_task = asyncio.create_task(self.stream_agent.ainvoke(messages.copy(), self.event_queue))

        mcp_agent_task = None
        if self.mcp_configs:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # 收集所有任务
        all_tasks = [task for task in [stream_agent_task, mcp_agent_task] if task is not None]

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


        stream_agent_messages = stream_agent_task.result() if  stream_agent_task and stream_agent_task.done() else None

        mcp_agent_messages = mcp_agent_task.result() if mcp_agent_task and mcp_agent_task.done() else None


        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)

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


    def invoke(self):
        pass

    def stream(self):
        pass

if __name__ == "__main__":
    pass