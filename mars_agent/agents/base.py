import inspect
import logging

from typing import List, Any
from pydantic import create_model

from mars_agent import MarsModelConfig
from mars_agent.agents.schema import BaseMessage
from mars_agent.core.mcp.manager import MCPManager
from mars_agent.core.models.manager import MarsModelManager
from mars_agent.schema import ModelConfig, MCPBaseConfig
from mars_agent.utils import mcp_tool_to_args_schema

logger = logging.getLogger(__name__)

class BaseAgent:

    def __init__(self,
                 name: str,
                 description: str = "",
                 model_config: ModelConfig = None,
                 system_prompt: str = "",
                 functions: List[Any] = []):

        self.name = name
        self.system_prompt = system_prompt
        self.description = description
        self.functions = functions

        self.conversation_model = self.set_conversation_model(model_config)


    async def ainvoke(self, messages: List[BaseMessage]):
        pass


    def set_conversation_model(self, model_config):
        return MarsModelManager.get_conversation_model(model_config)

    def agent_to_args_schema(self, func):
        sig = inspect.signature(func)
        fields = {
            name: (param.annotation, ... if param.default is inspect.Parameter.empty else param.default)
            for name, param in sig.parameters.items()
        }
        model = create_model(self.name, **fields)
        schema = model.model_json_schema()

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema
            },
        }



class MCPAgent(BaseAgent):
    def __init__(self, name: str,
                 description: str = "",
                 model_config: ModelConfig = None,
                 system_prompt: str = "",
                 mcp_config: MCPBaseConfig = None,
                 functions: List[Any] = []):
        super().__init__(name, description, model_config, system_prompt, functions)

        self.mcp_config = mcp_config
        self.mcp_manager = MCPManager([mcp_config])

    async def init_mcp_tools(self):
        """Initialize MCP tools - with error handling"""
        if not self.mcp_config:
            self.mcp_tools = []
            return

        try:
            # Establish connection with MCP Server
            self.mcp_tools = await self.mcp_manager.get_mcp_tools()


            for mcp_tool in self.mcp_tools:
                self.mcp_tools_schema.append(
                    mcp_tool_to_args_schema(mcp_tool.name, mcp_tool.description, mcp_tool.args_schema))

            logger.info(f"Loaded {len(self.mcp_tools)} MCP tools from MCP servers")

        except Exception as err:
            logger.error(f"Failed to initialize MCP tools: {err}")
            self.mcp_tools = []

    async def init_agent_tools(self):

