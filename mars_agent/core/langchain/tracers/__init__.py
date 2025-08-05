"""**Tracers** are classes for tracing runs.

**Class hierarchy:**

.. code-block::

    BaseCallbackHandler --> BaseTracer --> <name>Tracer  # Examples: LangChainTracer, RootListenersTracer
                                       --> <name>  # Examples: LogStreamCallbackHandler
"""  # noqa: E501

__all__ = [
    "BaseTracer",
    "EvaluatorCallbackHandler",
    "LangChainTracer",
    "ConsoleCallbackHandler",
    "Run",
    "RunLog",
    "RunLogPatch",
    "LogStreamCallbackHandler",
]

from mars_agent.core.langchain.tracers.base import BaseTracer
from mars_agent.core.langchain.tracers.evaluation import EvaluatorCallbackHandler
from mars_agent.core.langchain.tracers.langchain import LangChainTracer
from mars_agent.core.langchain.tracers.log_stream import (
    LogStreamCallbackHandler,
    RunLog,
    RunLogPatch,
)
from mars_agent.core.langchain.tracers.schemas import Run
from mars_agent.core.langchain.tracers.stdout import ConsoleCallbackHandler
