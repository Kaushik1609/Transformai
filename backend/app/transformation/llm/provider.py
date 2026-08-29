"""Abstract LLM provider contract shared by all Phase 7 generators."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Generate text from a system prompt and user content.

    Generators should treat this as a thin, replaceable text-generation
    boundary.  The provider is responsible only for returning a string;
    schema validation and prompt assembly are owned by the generators.
    """

    @abstractmethod
    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        """Return the generated text for the given prompts."""
