import asyncio
import json
import logging
from collections.abc import Awaitable
from typing import Callable, Union, List, AsyncGenerator, Dict

from mars_agent.core.tools import Tool
from mars_agent.schema import MarsModelConfig, MCPBaseConfig, MarsBaseChunk, MarsAIMessage
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.prompts.chat_prompt import FIX_JSON_PROMPT, SINGLE_PLAN_CALL_PROMPT, \
    PLAN_CALL_TOOL_PROMPT
from mars_agent.schema import MarsModelConfig, EventStatusType, EventAgentType, EventMessageType, EventTitleType, \
    PlanType
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.utils import function_to_args_schema, EventManager, EventType, convert_langchain_tool_calls, \
    mcp_tool_to_args_schema
from mars_agent.utils.util import get_current_time

logger = logging.getLogger(__name__)

class MarsMultiAgent:
    def __init__(self,
                 model_config: Union[dict, MarsModelConfig],
                 tool_call_model_config: Union[dict, MarsModelConfig] = None,
                 functions: List[Union[Callable[..., str], Callable[..., Awaitable[str]]]] = [],
                 mcp_configs: List[MCPBaseConfig] = [],
                 enable_runtime_logs: bool = True,
                 event_queue: asyncio.Queue = None):
        self.mcp_tools_schema = []
        self.functions = functions

        if not tool_call_model_config:
            self.tool_call_model_config = model_config
        else:
            self.tool_call_model_config = tool_call_model_config

        self.model_config = model_config

        self.enable_runtime_logs = enable_runtime_logs

        self.mcp_configs = mcp_configs
        self.mcp_manager = MCPManager(mcp_configs)

        self.event_queue = event_queue
        self.event_manager = EventManager(self.event_queue) if self.event_queue else EventManager()

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