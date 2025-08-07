"""
Mars Agent Utilities Module

This module contains various utility functions and managers used in the Mars Agent framework.

Main Components:
- util: Core utility functions
- event_manager: Event manager
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .util import (
        mcp_tool_to_args_schema,
        function_to_args_schema,
        convert_langchain_tool_calls,
        fix_json_quotes
    )
    from .event_manager import (
        EventManager,
        EventType
    )

# Compatible with old import methods, use lazy import to avoid circular dependencies

def __getattr__(name: str):
    if name in [
        'mcp_tool_to_args_schema',
        'function_to_args_schema', 
        'convert_langchain_tool_calls',
        'fix_json_quotes'
    ]:
        # Utility functions
        from .util import (
            mcp_tool_to_args_schema,
            function_to_args_schema,
            convert_langchain_tool_calls,
            fix_json_quotes
        )
        return locals()[name]
    
    elif name in ['EventManager', 'EventType']:
        # Event manager
        from .event_manager import EventManager, EventType
        return locals()[name]
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'") 