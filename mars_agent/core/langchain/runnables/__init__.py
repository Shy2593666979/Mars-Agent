"""LangChain **Runnable** and the **LangChain Expression Language (LCEL)**.

The LangChain Expression Language (LCEL) offers a declarative method to build
production-grade programs that harness the power of LLMs.

Programs created using LCEL and LangChain Runnables inherently support
synchronous, asynchronous, batch, and streaming operations.

Support for **async** allows servers hosting LCEL based programs to scale better
for higher concurrent loads.

**Batch** operations allow for processing multiple inputs in parallel.

**Streaming** of intermediate outputs, as they're being generated, allows for
creating more responsive UX.

This module contains schema and implementation of LangChain Runnables primitives.
"""

from mars_agent.core.langchain.runnables.base import (
    Runnable,
    RunnableBinding,
    RunnableGenerator,
    RunnableLambda,
    RunnableMap,
    RunnableParallel,
    RunnableSequence,
    RunnableSerializable,
    chain,
)
from mars_agent.core.langchain.runnables.branch import RunnableBranch
from mars_agent.core.langchain.runnables.config import (
    RunnableConfig,
    ensure_config,
    get_config_list,
    patch_config,
    run_in_executor,
)
from mars_agent.core.langchain.runnables.fallbacks import RunnableWithFallbacks
from mars_agent.core.langchain.runnables.history import RunnableWithMessageHistory
from mars_agent.core.langchain.runnables.passthrough import (
    RunnableAssign,
    RunnablePassthrough,
    RunnablePick,
)
from mars_agent.core.langchain.runnables.router import RouterInput, RouterRunnable
from mars_agent.core.langchain.runnables.utils import (
    AddableDict,
    ConfigurableField,
    ConfigurableFieldMultiOption,
    ConfigurableFieldSingleOption,
    ConfigurableFieldSpec,
    aadd,
    add,
)

__all__ = [
    "chain",
    "AddableDict",
    "ConfigurableField",
    "ConfigurableFieldSingleOption",
    "ConfigurableFieldMultiOption",
    "ConfigurableFieldSpec",
    "ensure_config",
    "run_in_executor",
    "patch_config",
    "RouterInput",
    "RouterRunnable",
    "Runnable",
    "RunnableSerializable",
    "RunnableBinding",
    "RunnableBranch",
    "RunnableConfig",
    "RunnableGenerator",
    "RunnableLambda",
    "RunnableMap",
    "RunnableParallel",
    "RunnablePassthrough",
    "RunnableAssign",
    "RunnablePick",
    "RunnableSequence",
    "RunnableWithFallbacks",
    "RunnableWithMessageHistory",
    "get_config_list",
    "aadd",
    "add",
]
