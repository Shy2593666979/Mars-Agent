"""**Callback handlers** allow listening to events in LangChain.

**Class hierarchy:**

.. code-block::

    BaseCallbackHandler --> <name>CallbackHandler  # Example: AimCallbackHandler
"""

from mars_agent.core.langchain.callbacks.base import (
    AsyncCallbackHandler,
    BaseCallbackHandler,
    BaseCallbackManager,
    CallbackManagerMixin,
    Callbacks,
    ChainManagerMixin,
    LLMManagerMixin,
    RetrieverManagerMixin,
    RunManagerMixin,
    ToolManagerMixin,
)
from mars_agent.core.langchain.callbacks.file import FileCallbackHandler
from mars_agent.core.langchain.callbacks.manager import (
    AsyncCallbackManager,
    AsyncCallbackManagerForChainGroup,
    AsyncCallbackManagerForChainRun,
    AsyncCallbackManagerForLLMRun,
    AsyncCallbackManagerForRetrieverRun,
    AsyncCallbackManagerForToolRun,
    AsyncParentRunManager,
    AsyncRunManager,
    BaseRunManager,
    CallbackManager,
    CallbackManagerForChainGroup,
    CallbackManagerForChainRun,
    CallbackManagerForLLMRun,
    CallbackManagerForRetrieverRun,
    CallbackManagerForToolRun,
    ParentRunManager,
    RunManager,
    adispatch_custom_event,
    dispatch_custom_event,
)
from mars_agent.core.langchain.callbacks.stdout import StdOutCallbackHandler
from mars_agent.core.langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from mars_agent.core.langchain.callbacks.usage import (
    UsageMetadataCallbackHandler,
    get_usage_metadata_callback,
)

__all__ = [
    "dispatch_custom_event",
    "adispatch_custom_event",
    "RetrieverManagerMixin",
    "LLMManagerMixin",
    "ChainManagerMixin",
    "ToolManagerMixin",
    "Callbacks",
    "CallbackManagerMixin",
    "RunManagerMixin",
    "BaseCallbackHandler",
    "AsyncCallbackHandler",
    "BaseCallbackManager",
    "BaseRunManager",
    "RunManager",
    "ParentRunManager",
    "AsyncRunManager",
    "AsyncParentRunManager",
    "CallbackManagerForLLMRun",
    "AsyncCallbackManagerForLLMRun",
    "CallbackManagerForChainRun",
    "AsyncCallbackManagerForChainRun",
    "CallbackManagerForToolRun",
    "AsyncCallbackManagerForToolRun",
    "CallbackManagerForRetrieverRun",
    "AsyncCallbackManagerForRetrieverRun",
    "CallbackManager",
    "CallbackManagerForChainGroup",
    "AsyncCallbackManager",
    "AsyncCallbackManagerForChainGroup",
    "StdOutCallbackHandler",
    "StreamingStdOutCallbackHandler",
    "FileCallbackHandler",
    "UsageMetadataCallbackHandler",
    "get_usage_metadata_callback",
]
