"""LangSmith Client."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mars_agent.core.langsmith._expect import expect
    from mars_agent.core.langsmith.async_client import AsyncClient
    from mars_agent.core.langsmith.client import Client
    from mars_agent.core.langsmith.evaluation import aevaluate, evaluate
    from mars_agent.core.langsmith.evaluation.evaluator import EvaluationResult, RunEvaluator
    from mars_agent.core.langsmith.run_helpers import (
        get_current_run_tree,
        get_tracing_context,
        trace,
        traceable,
        tracing_context,
    )
    from mars_agent.core.langsmith.run_trees import RunTree
    from mars_agent.core.langsmith.testing._internal import test, unit
    from mars_agent.core.langsmith.utils import ContextThreadPoolExecutor

# Avoid calling into importlib on every call to __version__

__version__ = "0.4.8"
version = __version__  # for backwards compatibility


def __getattr__(name: str) -> Any:
    if name == "__version__":
        return version
    elif name == "Client":
        from mars_agent.core.langsmith.client import Client

        return Client
    elif name == "AsyncClient":
        from mars_agent.core.langsmith.async_client import AsyncClient

        return AsyncClient
    elif name == "RunTree":
        from mars_agent.core.langsmith.run_trees import RunTree

        return RunTree
    elif name == "EvaluationResult":
        from mars_agent.core.langsmith.evaluation.evaluator import EvaluationResult

        return EvaluationResult
    elif name == "RunEvaluator":
        from mars_agent.core.langsmith.evaluation.evaluator import RunEvaluator

        return RunEvaluator
    elif name == "trace":
        from mars_agent.core.langsmith.run_helpers import trace

        return trace
    elif name == "traceable":
        from mars_agent.core.langsmith.run_helpers import traceable

        return traceable

    elif name == "test":
        from mars_agent.core.langsmith.testing._internal import test

        return test

    elif name == "expect":
        from mars_agent.core.langsmith._expect import expect

        return expect
    elif name == "evaluate":
        from mars_agent.core.langsmith.evaluation import evaluate

        return evaluate

    elif name == "evaluate_existing":
        from mars_agent.core.langsmith.evaluation import evaluate_existing

        return evaluate_existing
    elif name == "aevaluate":
        from mars_agent.core.langsmith.evaluation import aevaluate

        return aevaluate
    elif name == "aevaluate_existing":
        from mars_agent.core.langsmith.evaluation import aevaluate_existing

        return aevaluate_existing
    elif name == "tracing_context":
        from mars_agent.core.langsmith.run_helpers import tracing_context

        return tracing_context

    elif name == "get_tracing_context":
        from mars_agent.core.langsmith.run_helpers import get_tracing_context

        return get_tracing_context
    elif name == "get_current_run_tree":
        from mars_agent.core.langsmith.run_helpers import get_current_run_tree

        return get_current_run_tree

    elif name == "unit":
        from mars_agent.core.langsmith.testing._internal import unit

        return unit
    elif name == "ContextThreadPoolExecutor":
        from mars_agent.core.langsmith.utils import ContextThreadPoolExecutor

        return ContextThreadPoolExecutor

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Client",
    "RunTree",
    "__version__",
    "EvaluationResult",
    "RunEvaluator",
    "anonymizer",
    "traceable",
    "trace",
    "unit",
    "test",
    "expect",
    "evaluate",
    "aevaluate",
    "tracing_context",
    "get_tracing_context",
    "get_current_run_tree",
    "ContextThreadPoolExecutor",
    "AsyncClient",
]
