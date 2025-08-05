"""Code to help indexing data into a vectorstore.

This package contains helper logic to help deal with indexing data into
a vectorstore while avoiding duplicated content and over-writing content
if it's unchanged.
"""

from mars_agent.core.langchain.indexing.api import IndexingResult, aindex, index
from mars_agent.core.langchain.indexing.base import (
    DeleteResponse,
    DocumentIndex,
    InMemoryRecordManager,
    RecordManager,
    UpsertResponse,
)

__all__ = [
    "aindex",
    "DeleteResponse",
    "DocumentIndex",
    "index",
    "IndexingResult",
    "InMemoryRecordManager",
    "RecordManager",
    "UpsertResponse",
]
