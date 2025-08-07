"""
Mars Agent - AI agent system based on master-sub-agent architecture

This is a Python-based AI agent system designed with master-sub-agent architecture, supporting MCP protocol and streaming processing.
"""

__version__ = "0.1.0"
__author__ = "MingGuang Tian"

from .agent import MarsAgent
from .schema import MarsModelConfig, MCPBaseConfig, MCPSSEConfig, MCPStdioConfig

__all__ = [
    "MarsAgent",
    "MarsModelConfig", 
    "MCPBaseConfig",
    "MCPSSEConfig",
    "MCPStdioConfig"
]

