from __future__ import annotations

from app.core.config import settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider


class EmbeddingService:
    """Validates and normalizes text embeddings for chunk persistence."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider | None = None,
        dimensions: int | None = None,
    ):
        self.dimensions = dimensions if dimensions is not None else settings.EMBEDDING_DIMENSIONS
        self.provider = provider or FakeEmbeddingProvider(dimensions=self.dimensions)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not texts:
            raise ValueError("Embedding batch cannot be empty.")
        if any(not isinstance(text, str) for text in texts):
            raise ValueError("Embedding batch items must all be strings.")

        vectors = self.provider.embed_texts(texts)
        if len(vectors) != len(texts):
            raise ValueError(
                f"Embedding provider returned {len(vectors)} vectors for {len(texts)} texts."
            )

        normalized: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, list):
                raise ValueError("Each embedding must be returned as a list of floats.")
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Embedding dimensions mismatch: expected {self.dimensions}, got {len(vector)}."
                )
            normalized.append([float(value) for value in vector])
        return normalized
