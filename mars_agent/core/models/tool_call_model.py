import json
from typing import List, Dict, Any, Union

from mars_agent.core.langchain.messages import BaseMessage, ChatMessage, HumanMessage, AIMessage, FunctionMessage, ToolMessage, \
    SystemMessage, ToolCall
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from mars_agent.core.models.base_model import BaseMarsModel


class ToolCallModel(BaseMarsModel):
    def __init__(self, model: str, base_url: str, api_key: str,temperature=None):
        self.model_name = model
        self.temperature = temperature
        super().__init__(base_url=base_url, api_key=api_key)
        
    def bind_tools(self, tools: dict):
        self.tools = tools

    async def ainvoke(self, messages: List[BaseMessage]) -> ChatCompletionMessage:
        user_messages = [self.convert_message_to_dict(message) for message in messages]

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=user_messages,
            temperature=self.temperature,
            tools=self.tools
        )
        return response.choices[0].message

