"""
Mars Agent 工具模块

此模块包含 Mars Agent 框架中使用的各种工具函数和管理器。

Modules:
    util: 核心工具函数
    event_manager: 事件管理器
"""

from mars_agent.utils.util import (
    function_to_args_schema,
    convert_langchain_tool_calls,
    convert_openai_tool_calls,
    mcp_tool_to_args_schema,
    fix_json_text
)

from mars_agent.utils.event_manager import (
    EventType,
    StreamEvent,
    EventManager,
    get_global_event_manager,
    set_global_event_manager
)

__all__ = [
    # 工具函数
    "function_to_args_schema",
    "convert_langchain_tool_calls", 
    "convert_openai_tool_calls",
    "mcp_tool_to_args_schema",
    "fix_json_text",
    
    # 事件管理器
    "EventType",
    "StreamEvent", 
    "EventManager",
    "get_global_event_manager",
    "set_global_event_manager"
] 