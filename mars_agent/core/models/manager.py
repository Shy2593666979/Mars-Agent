from mars_agent.core.models.base_model import MarsModelConfig
from mars_agent.core.models.conversation_model import ConversationModel
from mars_agent.core.models.tool_call_model import ToolCallModel


class MarsModelManager:

    @classmethod
    def get_tool_call_model(cls, model_config: MarsModelConfig):
        return ToolCallModel(**model_config.model_dump())

    @classmethod
    def get_conversation_model(cls, model_config: MarsModelConfig) -> ConversationModel:
        return ConversationModel(**model_config.model_dump())
