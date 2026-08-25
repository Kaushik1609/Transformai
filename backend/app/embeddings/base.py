from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Provider-agnostic embedding interface for text chunks."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
