from pydantic import BaseModel
from typing import List, Any, Dict, Optional, Literal

class MCPConfig(BaseModel):
    url: str
    type: Literal["sse", "http", "stdio"]
    server_name: str
    user_config: dict
    max_step: int = 5