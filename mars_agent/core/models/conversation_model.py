from typing import List

from langchain_core.messages import BaseMessage
from openai.types.chat import ChatCompletionMessage

from mars_agent.core.models.base_model import BaseMarsModel


class ConversationModel(BaseMarsModel):
    def __init__(self, model: str, base_url: str, api_key: str, temperature: float=None):
        self.model_name = model
        self.temperature = temperature
        super().__init__(api_key=api_key, base_url=base_url)

    async def astream(self, messages: List[BaseMessage]):
        user_messages = [self.convert_message_to_dict(message) for message in messages]

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=user_messages,
            temperature=self.temperature,
            stream=True
        )
        async for chunk in response:
            yield chunk.choices[0].delta

    def bind_tools(self, tools: dict):
        self.tools = tools

    async def ainvoke(self, messages: List[BaseMessage]) -> ChatCompletionMessage:
        user_messages = [self.convert_message_to_dict(message) for message in messages]

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=user_messages,
            temperature=self.temperature,
        )
        return response.choices[0].message