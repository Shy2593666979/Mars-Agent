import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from typing import List, Any, Dict, Optional, Literal, Union


class ProgressModel(BaseModel):
    agent: str
    title: str
    message: str
    status: str

class ResponseModel(BaseModel):
    content: str
    accumulated: str
    additional_data: Optional[Dict[str, Any]] = None

class MarsBaseChunk(BaseModel):
    type: str
    timestamp: float

class MarsProgressChunk(MarsBaseChunk):
    type: str = "process"
    data: ProgressModel

class MarsResponseChunk(MarsBaseChunk):
    type: str = "response"
    data: ResponseModel

class MarsHeartbeatChunk(MarsBaseChunk):
    type: str = "heartbeat"
    data: Dict[str, Any]

class MarsAIMessage(BaseModel):
    type: str = "assistant"
    content: Union[str, list[Union[str, dict]]]
    metadata: Union[str, Dict] = None

class MCPBaseConfig(BaseModel):
    server_name: str
    transport: str
    personal_config: Optional[Dict[str, Any]] = None

class MCPSSEConfig(MCPBaseConfig):
    transport: Literal["sse"] = "sse"
    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    sse_read_timeout: Optional[float] = None
    session_kwargs: Optional[Dict[str, Any]] = None

class MCPStdioConfig(MCPBaseConfig):
    transport: Literal["stdio"] = "stdio"
    command: str
    args: list[str]
    env: Optional[Dict[str, str]] = None
    cwd: Optional[Path] = None
    encoding: str = "utf-8"
    encoding_error_handler: Optional[str] = "ignore"
    session_kwargs: Optional[Dict[str, Any]] = None

class MCPStreamableHttpConfig(MCPBaseConfig):
    transport: Literal["streamable_http"] = "streamable_http"
    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    sse_read_timeout: Optional[float] = None
    terminate_on_close: Optional[bool] = None
    session_kwargs: Optional[Dict[str, Any]] = None


class MCPWebsocketConfig(MCPBaseConfig):
    transport: Literal["websocket"] = "websocket"
    url: str
    session_kwargs: Optional[Dict[str, Any]] = None

class MarsModelConfig(BaseModel):
    model: str = Field(..., description="Name of the model")
    base_url: str = Field(..., description="Base URL for the model API")
    api_key: str = Field(..., description="API key for the model")
    temperature: float = Field(default=0.6, description="Temperature value for the model")


class PlanType:
    CALL_USER = "request_missing_param"

    TOOL_NAME = "tool name"
    TOOL_ARGS = "tool args"
    MESSAGE = "message"

class EventStatusType:
    """事件状态常量"""
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"
    START = "START"
    END = "END"
    PROGRESS = "PROGRESS"


class EventAgentType:
    """事件代理类型"""
    MARS_AGENT = "Mars Agent"
    MCP_AGENT = "MCP Agent - {server_name}"
    STREAM_AGENT = "Stream Agent"
    PLAN_AGENT = "Plan Agent"


class EventTitleType:
    """事件标题类型"""
    # 工具选择相关
    SELECT_TOOL = "Start Selecting Available Tools"
    CONTINUE_SELECT_TOOL = "Need To Continue Calling Tools?"
    
    # MCP 工具执行相关
    EXECUTE_MCP_TOOL = "Execute MCP Tool: {tool_name}"
    
    # 插件工具执行相关
    EXECUTE_PLUGIN_TOOL = "Execute Plugin Tool: {tool_name}"

    # 整合工具执行相关
    EXECUTE_TOOL = "Execute Tool: {tool_name}"


    # Stream Agent 相关
    STREAM_AGENT_START = "Stream Agent"
    
    # 模型响应相关
    MODEL_RESPONSE = "Model Response"
    MODEL_RESPONSE_ERROR = "Model Response Error"

    # Plan 相关
    PLAN_ACTIONS = "Start Build Tools Plan"

    # 修复Json
    FIX_PLAN_JSON = "Fix Plan Json Data"



class EventMessageType:
    """事件消息类型"""
    # 工具调用消息
    CALL_MCP_TOOL = "Calling MCP tool {tool_name}..."
    
    CALL_PLUGIN_TOOL = "Calling plugin tool {tool_name}..."

    CALL_TOOL = "Calling tool {tool_name}..."
    
    # 可用工具消息
    AVAILABLE_MCP_TOOL = "Available MCP Tools Under {server_name}: {tool_name}"
    
    AVAILABLE_PLUGIN_TOOL = "Available Plugin Tools: {tool_name}"
    
    AVAILABLE_TOOLS = "Available tools: {tool_name}"
    
    # 通用消息
    NO_AVAILABLE_TOOL = "No available tools found"
    
    # 执行过程消息
    ANALYZING_TOOLS = "Analyzing tools to use..."
    STARTING_TOOL_EXECUTION = "Starting tool execution..."
    TOOL_EXECUTION_COMPLETED = "Tool execution completed, executed {tool_count} tools"
    
    NO_TOOLS_NEEDED = "No tools need to be executed"
    
    # MCP Agent 消息
    MCP_AGENT_STARTING = "Starting MCP tool execution..."
    
    MCP_AGENT_COMPLETED = "MCP tool execution completed, executed {tool_count} tools"
    MCP_AGENT_NO_TOOLS = "No MCP tools need to be executed"
    
    ANALYZING_MCP_TOOLS = "Analyzing tools to use under {server_name}..."
    
    START_TOOLS_PLAN = "Start Tools Plan"

    END_TOOLS_PLAN = "Tools Plan: {content}"

    START_FIX_JSON = "Start Fix Plan Json Data"

    END_FIX_JSON = "Fix Plan Json: {fix_content}"


    # 错误消息
    TOOL_ERROR = "{err}"
    
    EXECUTION_FAILED = "Execution failed: {err}"

    FIX_JSON_ERROR = "Fix Json Failed: {err}"

    TOOLS_PLAN_ERROR = "Tools Plan Failed: {err}"

    # 模型响应消息
    GENERATING_RESPONSE = "Generating response..."
    RESPONSE_COMPLETED = "Response generation completed"


