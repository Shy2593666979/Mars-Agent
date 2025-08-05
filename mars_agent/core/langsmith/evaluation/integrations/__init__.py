"""This module provides integration wrappers for popular open source eval frameworks.

to be used with LangSmith.
"""

from mars_agent.core.langsmith.evaluation.integrations._langchain import LangChainStringEvaluator

__all__ = ["LangChainStringEvaluator"]
