"""Provider-neutral content analysis contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ContentAnalysisProvider(ABC):
    """Analyze normalized source text into a JSON-compatible mapping."""

    @abstractmethod
    def analyze(self, text: str, chunks: list[dict]) -> dict:
        """Return candidate canonical content; validation happens downstream."""
