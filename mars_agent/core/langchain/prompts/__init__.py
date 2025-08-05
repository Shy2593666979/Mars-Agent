"""**Prompt** is the input to the model.

Prompt is often constructed
from multiple components and prompt values. Prompt classes and functions make constructing
 and working with prompts easy.

**Class hierarchy:**

.. code-block::

    BasePromptTemplate --> PipelinePromptTemplate
                           StringPromptTemplate --> PromptTemplate
                                                    FewShotPromptTemplate
                                                    FewShotPromptWithTemplates
                           BaseChatPromptTemplate --> AutoGPTPrompt
                                                      ChatPromptTemplate --> AgentScratchPadChatPromptTemplate



    BaseMessagePromptTemplate --> MessagesPlaceholder
                                  BaseStringMessagePromptTemplate --> ChatMessagePromptTemplate
                                                                      HumanMessagePromptTemplate
                                                                      AIMessagePromptTemplate
                                                                      SystemMessagePromptTemplate

"""  # noqa: E501

from mars_agent.core.langchain.prompts.base import (
    BasePromptTemplate,
    aformat_document,
    format_document,
)
from mars_agent.core.langchain.prompts.chat import (
    AIMessagePromptTemplate,
    BaseChatPromptTemplate,
    ChatMessagePromptTemplate,
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)
from mars_agent.core.langchain.prompts.few_shot import (
    FewShotChatMessagePromptTemplate,
    FewShotPromptTemplate,
)
from mars_agent.core.langchain.prompts.few_shot_with_templates import FewShotPromptWithTemplates
from mars_agent.core.langchain.prompts.loading import load_prompt
from mars_agent.core.langchain.prompts.pipeline import PipelinePromptTemplate
from mars_agent.core.langchain.prompts.prompt import PromptTemplate
from mars_agent.core.langchain.prompts.string import (
    StringPromptTemplate,
    check_valid_template,
    get_template_variables,
    jinja2_formatter,
    validate_jinja2,
)

__all__ = [
    "AIMessagePromptTemplate",
    "BaseChatPromptTemplate",
    "BasePromptTemplate",
    "ChatMessagePromptTemplate",
    "ChatPromptTemplate",
    "FewShotPromptTemplate",
    "FewShotPromptWithTemplates",
    "FewShotChatMessagePromptTemplate",
    "HumanMessagePromptTemplate",
    "MessagesPlaceholder",
    "PipelinePromptTemplate",
    "PromptTemplate",
    "StringPromptTemplate",
    "SystemMessagePromptTemplate",
    "load_prompt",
    "format_document",
    "aformat_document",
    "check_valid_template",
    "get_template_variables",
    "jinja2_formatter",
    "validate_jinja2",
]
