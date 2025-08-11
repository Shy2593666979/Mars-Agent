"""
Mars Agent - AI agent system based on master-sub-agent architecture

This is a Python-based AI agent system designed with master-sub-agent architecture, supporting MCP protocol and streaming processing.
"""

__version__ = "0.1.0"
__author__ = "MingGuang Tian"

from .agents.mars_agent import MarsAgent
from .agents.plan_agent import MarsPlanAgent
from .schema import MarsModelConfig, MCPBaseConfig, MCPSSEConfig, MCPStdioConfig, MCPStreamableHttpConfig, \
    MarsAIMessage, MarsProgressChunk, MarsResponseChunk, MarsHeartbeatChunk

__all__ = [
    "MarsAgent",
    "MarsPlanAgent",
    "MarsModelConfig",
    "MCPBaseConfig",
    "MCPSSEConfig",
    "MCPStdioConfig",
    "MCPStreamableHttpConfig",
    "MarsAIMessage",
    "MarsProgressChunk",
    "MarsResponseChunk",
    "MarsHeartbeatChunk"
]
