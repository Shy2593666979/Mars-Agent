from pydantic import BaseModel, Field
from typing import List, Any, Dict, Optional, Literal

class MCPConfig(BaseModel):
    url: str
    type: Literal["sse", "http", "stdio"]
    server_name: str
    user_config: dict
    max_step: int = 5

class MarsModelConfig(BaseModel):
    model: str = Field(..., description="模型的名称")
    base_url: str = Field(..., description="模型配置")
    api_key: str = Field(..., description="模型密钥")
    temperature: float = Field(default=0.6, description="模型的温度值")