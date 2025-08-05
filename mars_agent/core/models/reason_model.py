from typing import List, Dict, Any, Union

from mars_agent.core.langchain.messages import BaseMessage, ChatMessage, HumanMessage, AIMessage, FunctionMessage, ToolMessage, \
    SystemMessage, ToolCall

from mars_agent.core.models.base_model import BaseMarsModel


class ReasoningModel(BaseMarsModel):
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float=None):
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
        return response


