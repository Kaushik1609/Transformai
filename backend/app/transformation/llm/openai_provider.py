"""OpenAI-backed LLM provider wired through the existing LLM_* settings.

The provider stays model-agnostic at the application layer: model, API key,
temperature, max tokens and timeout are read from the environment via
`app.core.config.settings`.  The API key is never exposed to callers.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.transformation.llm.provider import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """Generate text using an OpenAI-compatible chat model via langchain."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> None:
        self._model = model or settings.LLM_MODEL
        self._api_key = api_key or settings.LLM_API_KEY
        self._temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self._max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS
        self._timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS
        if not self._api_key:
            raise ValueError(
                "LLM_API_KEY is not configured. Set LLM_API_KEY in the environment "
                "or use FakeLLMProvider for offline/tests."
            )
        self._client = ChatOpenAI(
            model=self._model,
            api_key=self._api_key,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout=self._timeout,
        )

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        response = self._client.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenAI provider returned empty content.")
        return content.strip()
