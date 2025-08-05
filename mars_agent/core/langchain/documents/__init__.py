"""Documents module.

**Document** module is a collection of classes that handle documents
and their transformations.

"""

from mars_agent.core.langchain.documents.base import Document
from mars_agent.core.langchain.documents.compressor import BaseDocumentCompressor
from mars_agent.core.langchain.documents.transformers import BaseDocumentTransformer

__all__ = ["Document", "BaseDocumentTransformer", "BaseDocumentCompressor"]
