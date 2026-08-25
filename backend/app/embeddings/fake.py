from __future__ import annotations

import hashlib

from app.embeddings.base import EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider used for tests and local validation."""

    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector: list[float] = []
        for index in range(self.dimensions):
            byte_sample = digest[(index * 3) % len(digest)]
            value = (byte_sample / 255.0) * 2.0 - 1.0
            vector.append(float(value))
        return vector

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list):
            raise ValueError("Embedding input must be a list of strings.")
        return [self._embed_one(text) for text in texts]
