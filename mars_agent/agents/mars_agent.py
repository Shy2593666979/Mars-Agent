import asyncio
import time
import logging
from typing import List, Callable, Union, Any, Dict
from collections.abc import Awaitable
from uuid import uuid4
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage

from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType, \
    MarsAIMessage
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.agents.mcp_agent import MCPAgent
from mars_agent.agents.stream_agent import StreamingAgent
from mars_agent.schema import MCPBaseConfig
from mars_agent.utils.event_manager import EventManager, EventType

logger = logging.getLogger(__name__)


class MarsAgent:
    """MarsAgent

    The **main entry-point** of the Mars-Agent SDK.  It orchestrates every component involved in the
    conversation:

    • Handles memory, event routing and error reporting.
    • Delegates tool execution to the sub-agents (:class:`mars_agent.agents.streaming_agent.StreamingAgent`
      and :class:`mars_agent.agents.mcp_agent.MCPAgent`).
    • Calls the large-language model to generate the final natural-language response.

    Architecture
    ------------
    1. *MarsAgent* – main controller, owns the LLM and the global :class:`mars_agent.utils.event_manager.EventManager`.
    2. *StreamingAgent* – executes local plugin functions (and optionally MCP tools) in parallel.
    3. *MCPAgent* – executes remote tools registered on MCP servers.

    Typical Usage
    -------------

    ```python
    import asyncio
    from mars_agent.agent import MarsAgent
    from mars_agent.schema import MarsModelConfig, MCPSSEConfig

    async def main():
        agent = MarsAgent(
            # Tool-calling model used to decide which tool should be invoked
            tool_call_model_config=MarsModelConfig(model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
                                                  api_key="<your-key>",
                                                  base_url="https://api-inference.modelscope.cn/v1"),

            # Conversation model that actually writes the reply
            model_config=MarsModelConfig(model="qwen-plus",
                                         api_key="<your-key>",
                                         base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),

            # Register ordinary Python functions as plugin tools
            functions=[lambda location: f"Weather in {location} looks great!"],

            # (Optional) Register MCP servers so their remote tools can be leveraged
            mcp_configs=[
                MCPSSEConfig(server_name="Maps", url="https://example.com/sse")
            ],

            # Let MCPAgent run as an independent sub-agent
            mcp_as_agent=True
        )

        async for event in agent.astream("Hello, how's the weather in Beijing?"):
            # Each event is a dict produced by EventManager
            print(event)

    if __name__ == "__main__":
        asyncio.run(main())
    ```
    """
    
    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 mars_agent_id: str = None,
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 memory_path: str = None,
                 mcp_as_agent: bool = True,
                 enable_memory: bool = True,
                 enable_runtime_logs: bool = True,
                 enable_mcp_concurrency: bool = True,
                 mcp_configs: List[MCPBaseConfig] = []):

        self.mcp_agents: List[MCPAgent] = []
        self.mcp_configs = mcp_configs

        # When Tool Call model is not set, let Tool Call model be consistent with Conversation model
        if not tool_call_model_config:
            self.tool_call_model_config = model_config
        else:
            self.tool_call_model_config = tool_call_model_config

        self.model_config = model_config

        self.enable_mcp_concurrency = enable_mcp_concurrency
        self.mcp_as_agent = mcp_as_agent
        self.enable_memory = enable_memory
        self.functions = functions
        self.enable_runtime_logs = enable_runtime_logs
        self._mars_agent_id = mars_agent_id if mars_agent_id else uuid4().hex

        # Main agent's event queue and event manager - handle all events
        self.event_queue = asyncio.Queue()
        self.event_manager = EventManager(self.event_queue)
        
        # Initialize state management
        self._initialized = False
        self.stream_agent = None
        self.conversation_model = None

        self.event_process_logs = []
        self.init_mars_agent()


    async def emit_event(self, data: Dict[Any, Any]):
        """Main agent's event sending method - uniform event format"""
        await self.event_manager.emit_event(
            self.event_manager.create_event(EventType.EVENT, data)
        )


    def init_mars_agent(self):
        """Initialize main agent and all sub-agents - with resource management"""
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

            # Main agent is responsible for model invocation
            self.conversation_model = MarsModelManager.get_conversation_model(self.model_config)
            
            self._initialized = True
            logger.info("Mars Agent initialized successfully")
            
        except Exception as err:
            logger.error(f"Failed to initialize Mars Agent: {err}")
            raise

    def init_mcp_agents(self):
        """Initialize MCP Agent, pass the main agent's event queue"""
        self.mcp_agents = []
        for mcp_config in self.mcp_configs:
            # Pass the main agent's event queue to sub-agents to achieve unified event management
            mcp_agent = MCPAgent(mcp_config,
                                 self.model_config,
                                 self.tool_call_model_config,
                                 self.event_queue)  # Sub-agent uses the main agent's event queue
            self.mcp_agents.append(mcp_agent)

    def init_stream_agent(self):
        """Initialize Stream Agent, pass the main agent's event queue"""
        try:
            if self.mcp_as_agent:
                self.stream_agent = StreamingAgent(self.model_config,
                                                   self.tool_call_model_config,
                                                   functions=self.functions,
                                                   event_queue=self.event_queue)  # Sub-agent uses the main agent's event queue
            else:
                self.stream_agent = StreamingAgent(self.model_config,
                                                   self.tool_call_model_config,
                                                   functions=self.functions,
                                                   mcp_configs=self.mcp_configs,
                                                   event_queue=self.event_queue)  # Sub-agent uses the main agent's event queue
            
        except Exception as err:
            logger.error(f"Failed to initialize Stream Agent: {err}")
            raise

    @property
    def mars_agent_id(self):
        return self._mars_agent_id

    async def call_mcp_agent_messages(self, messages: List[BaseMessage]):
        """Invoke MCP Agent to execute tools, events automatically reported to main agent"""

        async def process_mcp_agent(mcp_agent: MCPAgent):
            # MCP Agent executes tools, events automatically sent to main agent event queue
            try:
                # Fix: Remove the initialization call here, the connection is managed uniformly in the main agent
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

        # Get MCP Agent information and return
        mcp_agent_messages: List[BaseMessage] = []
        for result in results:
            if isinstance(result, list):
                mcp_agent_messages.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"MCP Agent execution failed: {result}")
        return mcp_agent_messages

    async def call_stream_agent_messages(self, messages: List[BaseMessage]):
        """Invoke Stream Agent to execute tools, events automatically reported to main agent"""
        if self.functions and self.stream_agent:
            try:
                # Stream Agent executes tools, events automatically sent to main agent event queue
                return await self.stream_agent.ainvoke(messages)
            except Exception as err:
                logger.error(f"Stream Agent execution failed: {err}")
                return []
        return []

    def get_event_process_logs(self):
        """Run logs from start to finish according to Agent type"""
        event_process_logs = {}
        for event in self.event_process_logs:
            data = event.data
            if event.type == EventType.PROGRESS.value:
                event_process_logs[data.agent] = event_process_logs.get(data.agent, [])
                event_process_logs[data.agent].append(data)
        return event_process_logs

    async def ainvoke(self, messages: Union[str, BaseMessage, List[BaseMessage]]) -> MarsAIMessage:
        """Main agent's non-streaming invocation - unify sub-agent results and model replies"""
        if not self._initialized:
            self.init_mars_agent()
            
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        # Parallel invocation of sub-agents
        stream_agent_task = None
        if self.functions:
            stream_agent_task = asyncio.create_task(self.call_stream_agent_messages(messages.copy()))

        mcp_agent_task = None
        if self.mcp_configs and self.mcp_as_agent:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # Wait for sub-agents to complete
        if stream_agent_task:
            stream_agent_messages = await stream_agent_task
        else:
            stream_agent_messages = None

        if mcp_agent_task:
            mcp_agent_messages = await mcp_agent_task
        else:
            mcp_agent_messages = None

        # Merge sub-agent results
        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)

        # Main agent is responsible for final model invocation
        try:
            response = await self.conversation_model.ainvoke(messages)
            return MarsAIMessage(content=response.content)
        except Exception as err:
            logger.error(f"Main agent model invocation failed: {err}")
            raise


    async def astream(self, messages: Union[str, BaseMessage, List[BaseMessage]]):
        """Main agent's streaming invocation - unify event streams and model replies"""
        # if not self._initialized:
        #     await self.init_mars_agent()
            
        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]
        elif isinstance(messages, BaseMessage):
            messages = [messages]

        # Parallel start sub-agent tasks
        stream_agent_task = None
        if self.functions:
            stream_agent_task = asyncio.create_task(self.call_stream_agent_messages(messages.copy()))

        mcp_agent_task = None
        if self.mcp_configs and self.mcp_as_agent:
            mcp_agent_task = asyncio.create_task(self.call_mcp_agent_messages(messages.copy()))

        # Collect all sub-agent tasks
        all_tasks = [task for task in [stream_agent_task, mcp_agent_task] if task is not None]

        # Main agent uniformly handles event streams - receive all events from sub-agents
        async for event in self.event_manager.stream_with_heartbeat(all_tasks):
            # Only when runtime logs are enabled
            if self.enable_runtime_logs:
                self.event_process_logs.append(event)
                yield event

        # Wait for sub-agents to complete and collect results
        stream_agent_messages = stream_agent_task.result() if stream_agent_task and stream_agent_task.done() else None
        mcp_agent_messages = mcp_agent_task.result() if mcp_agent_task and mcp_agent_task.done() else None

        # Merge sub-agent tool execution results
        if stream_agent_messages:
            messages.extend(stream_agent_messages)

        if mcp_agent_messages:
            messages.extend(mcp_agent_messages)

        # Main agent is responsible for final model reply streaming
        response_content = ""
        try:
            # Send model reply start event
            await self.event_manager.emit_progress(
                EventTitleType.MODEL_RESPONSE,
                EventMessageType.GENERATING_RESPONSE,
                EventStatusType.START,
                EventAgentType.MARS_AGENT
            )
            
            async for chunk in self.conversation_model.astream(messages):
                if chunk.content:
                    response_content += chunk.content
                    # Main agent uniformly handles response chunk events
                    yield self.event_manager.create_response_chunk_event(chunk.content, response_content)

            # Send model reply completion event
            await self.event_manager.emit_progress(
                EventTitleType.MODEL_RESPONSE,
                EventMessageType.RESPONSE_COMPLETED,
                EventStatusType.END,
                EventAgentType.MARS_AGENT
            )
            
        # Main agent uniformly handles errors
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

    def invoke(self):
        """Synchronous invocation interface (to be implemented)"""
        pass

    def stream(self):
        """Synchronous streaming interface (to be implemented)"""
        pass


if __name__ == "__main__":
    pass