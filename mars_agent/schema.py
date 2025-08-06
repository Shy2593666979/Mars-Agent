from pathlib import Path

from pydantic import BaseModel, Field
from typing import List, Any, Dict, Optional, Literal

class MCPBaseConfig(BaseModel):
    server_name: str
    transport: str

class MCPSSEConfig(MCPBaseConfig):
    transport: Literal["sse"] = "sse"
    url: str
    personal_config: Optional[Dict[str, Any]] = None
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
    encoding_error_handler: Optional[str] = None
    session_kwargs: Optional[Dict[str, Any]] = None

class MCPStreamableHttpConfig(MCPBaseConfig):
    transport: Literal["streamable_http"] = "streamable_http"
    url: str
    personal_config: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    sse_read_timeout: Optional[float] = None
    terminate_on_close: Optional[bool] = None
    session_kwargs: Optional[Dict[str, Any]] = None


class MCPWebsocketConfig(MCPBaseConfig):
    transport: Literal["websocket"] = "websocket"
    url: str
    personal_config: Optional[Dict[str, Any]] = None
    session_kwargs: Optional[Dict[str, Any]] = None

class MarsModelConfig(BaseModel):
    model: str = Field(..., description="模型的名称")
    base_url: str = Field(..., description="模型配置")
    api_key: str = Field(..., description="模型密钥")
    temperature: float = Field(default=0.6, description="模型的温度值")