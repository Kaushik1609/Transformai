"""Local/offline LLM provider for Phase 2I air-gapped execution.

Supports OpenAI-compatible local inference engines (e.g. Ollama, vLLM, LocalAI,
TGI) running on-premises or on localhost without external network access or cloud
API credentials.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.transformation.llm.provider import LLMProvider


class LocalLLMProvider(LLMProvider):
    """Generate text using a local/on-premises OpenAI-compatible model endpoint."""

    is_external: bool = False
    is_local: bool = True
    requires_network: bool = False
    supports_offline: bool = True

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._model = (
            model
            or getattr(settings, "LOCAL_LLM_MODEL", None)
            or getattr(settings, "LLM_MODEL", "llama-3-8b")
        )
        self._base_url = (
            base_url
            or getattr(settings, "LOCAL_LLM_BASE_URL", "")
            or getattr(settings, "LLM_BASE_URL", "")
        )
        self._api_key = api_key or "local-no-key-required"
        self._temperature = (
            temperature if temperature is not None else settings.LLM_TEMPERATURE
        )
        self._max_tokens = (
            max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS
        )
        self._timeout = (
            timeout
            if timeout is not None
            else getattr(settings, "LOCAL_LLM_TIMEOUT", None)
            or settings.LLM_TIMEOUT_SECONDS
        )
        self._max_retries = (
            max_retries
            if max_retries is not None
            else settings.LLM_SDK_MAX_RETRIES
        )

        clean_url = (self._base_url or "").strip()
        if not clean_url:
            raise ValueError(
                "Local LLM provider requires LOCAL_LLM_BASE_URL or LLM_BASE_URL to be set."
            )

        self._client = ChatOpenAI(
            model=self._model,
            api_key=self._api_key,
            base_url=clean_url,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    @property
    def model(self) -> str:
        """Configured model identifier."""
        return self._model

    @property
    def base_url(self) -> str:
        """Configured local base URL."""
        return self._base_url

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        """Generate text via the local model endpoint."""
        response = self._client.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Local LLM provider returned empty content.")
        return content.strip()
