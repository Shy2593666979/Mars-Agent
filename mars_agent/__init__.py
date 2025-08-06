"""
Mars Agent - 基于主副代理架构的AI代理系统
"""

__version__ = "0.1.0"
__author__ = "MingGuang Tian"
__email__ = "2593666979@qq.com"

from mars_agent.schema import MarsModelConfig, MCPSSEConfig, MCPStdioConfig, MCPWebsocketConfig, MCPStreamableHttpConfig
from mars_agent.agent import MarsAgent

__all__ = [
    "MarsAgent",
    "MarsModelConfig", 
    "MCPSSEConfig",
    "MCPStdioConfig", 
    "MCPWebsocketConfig",
    "MCPStreamableHttpConfig",
]

