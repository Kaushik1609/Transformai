"""Embedding provider abstractions for Phase 3E (extended in Phase 11G)."""

from app.embeddings.base import EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.factory import (
    SUPPORTED_EMBEDDING_PROVIDERS,
    build_embedding_provider,
    build_resilient_embedding_provider,
)
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.embeddings.resilience import EmbeddingResilientProvider
from app.embeddings.service import EmbeddingService

__all__ = [
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "EmbeddingService",
    "OpenAIEmbeddingProvider",
    "EmbeddingResilientProvider",
    "SUPPORTED_EMBEDDING_PROVIDERS",
    "build_embedding_provider",
    "build_resilient_embedding_provider",
]
