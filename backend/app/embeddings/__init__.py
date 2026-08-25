"""Embedding provider abstractions for Phase 3E."""

from app.embeddings.base import EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.service import EmbeddingService

__all__ = ["EmbeddingProvider", "FakeEmbeddingProvider", "EmbeddingService"]
