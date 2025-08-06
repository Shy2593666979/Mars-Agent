import asyncio
import inspect
import json
from typing import List

from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, SystemMessage, ToolCall, HumanMessage

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from pydantic import create_model


# 将函数转成function schema格式
def function_to_args_schema(func) -> dict:
    """
    Converts a Python function into a JSON-serializable dictionary
    that describes the function's signature, including its name,
    description, and parameters.

    Args:
        func: The function to be converted.

    Returns:
        A dictionary representing the function's signature in JSON format.
    """
    sig = inspect.signature(func)
    fields = {
        name: (param.annotation, ... if param.default is inspect.Parameter.empty else param.default)
        for name, param in sig.parameters.items()
    }
    model = create_model(func.__name__, **fields)
    schema = model.model_json_schema()

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__ or "",
            "parameters": schema
        },
    }

# 将OpenAI的function call格式转成Langchain格式做适配
def convert_langchain_tool_calls(tool_calls: List[ChatCompletionMessageToolCall]):
    langchain_tool_calls: List[ToolCall] = []

    for tool_call in tool_calls:
        langchain_tool_calls.append(
            ToolCall(id=tool_call.id, args=json.loads(fix_json_text(tool_call.function.arguments)), name=tool_call.function.name))

    return langchain_tool_calls


# 将Langchain的格式转为OpenAI的格式适配
def convert_openai_tool_calls(self, tool_calls: List[ToolCall]):
    openai_tool_calls: List[ChatCompletionMessageToolCall] = []

    for tool_call in tool_calls:
        openai_tool_calls.append(ChatCompletionMessageToolCall(id=tool_call["id"], type="function",
                                                               function=Function(
                                                                   arguments=json.dumps(tool_call["args"]),
                                                                   name=tool_call["name"])))

    return openai_tool_calls


def mcp_tool_to_args_schema(name, description, args_schema) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": args_schema
        }
    }


def fix_json_text(text: str):
    """
    Json字符串不允许出现 ' 单引号
    修复Json字符串"""
    return text.replace("'", '"')