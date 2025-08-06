import asyncio
import logging
from typing import List

from langchain_core.tools import BaseTool
from mars_agent.core.mcp.multi_client import MultiServerMCPClient
from mars_agent.schema import MCPBaseConfig

logger = logging.getLogger(__name__)

HIDE_FIELDS = ["server_name", "personal_config"]

class MCPManager:
    def __init__(self, mcp_configs: List[MCPBaseConfig], timeout=10):

        connection_info = {
            mcp_config.server_name: mcp_config.model_dump(exclude={"server_name", "personal_config"})
            for mcp_config in mcp_configs
        }

        self.multi_server_client = MultiServerMCPClient(connection_info)
        self.mcp_configs = mcp_configs

        self.timeout = timeout


    async def get_mcp_tools(self) -> list[BaseTool]:
        tools = await self.multi_server_client.get_tools()
        return tools

    async def show_mcp_tools(self) -> dict:
        result = {}
        try:
            for mcp_config in self.mcp_configs:
                server_tools = await self.multi_server_client.get_tools(server_name=mcp_config.server_name)
                tool_list = []
                for tool in server_tools:
                    input_schema = tool.args_schema
                    tool_dict = {
                        'name': tool.name,
                        'description': tool.description,
                        'input_schema': input_schema
                    }
                    tool_list.append(tool_dict)
                result[mcp_config.server_name] = tool_list
        except Exception as err:
            logger.info(f"获取MCP 服务工具列表出错: {err}")
        return result


    async def call_mcp_tools(self, mcp_tools_args, is_concurrent=True):
        tool_results = []
        callable_tools = {}
        try:
            # 获取工具列表
            mcp_tools = await self.multi_server_client.get_tools()
            for tool in mcp_tools:
                callable_tools[tool.name] = tool
            # 异步并发
            if is_concurrent:
                # 创建异步任务列表
                tasks = []
                for tool_args in mcp_tools_args:
                    tool_name = tool_args["tool_name"]
                    tool_args = tool_args["tool_args"]
                    # 创建异步任务
                    task = asyncio.create_task(callable_tools[tool_name].coroutine(**tool_args))
                    tasks.append(task)
                # 并发执行所有任务
                for task in asyncio.as_completed(tasks):
                    try:
                        result = await task
                        tool_results.append(result)
                    except Exception as e:
                        logger.error(f"执行工具时出错: {e}")
            else:
                for tool_args in mcp_tools_args:
                    tool_name = tool_args["tool_name"]
                    tool_args = tool_args["tool_args"]
                    try:
                        result = await callable_tools[tool_name].coroutine(**tool_args)
                        tool_results.append(result)
                    except Exception as e:
                        tool_results.append(f"执行工具 {tool_name} 时出错: {e}")
                        logger.error(f"执行工具 {tool_name} 时出错: {e}")

        except Exception as err:
            logger.error(f"调用工具发生错误：{err}")
        return tool_results
