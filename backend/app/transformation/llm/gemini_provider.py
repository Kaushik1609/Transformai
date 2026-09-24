"""Gemini-backed LLM provider (OpenAI-compatible interface).

Uses Google's documented OpenAI-compatible endpoint
``https://generativelanguage.googleapis.com/v1beta/openai/`` via the standard
``openai`` SDK, so Gemini can be selected with ``LLM_PROVIDER=gemini`` without
adding a vendor-specific SDK.  Model, API key, base URL, temperature, max
tokens and timeout are read from the environment via ``app.core.config.settings``
and are overridable per-instance for tests.  The API key is never exposed to
callers and provider errors are re-raised with any credential redacted.

Structured output: the generators ask for a single JSON object and the OpenAI
compatibility layer accepts ``response_format={"type": "json_object"}`` on
Gemini chat completions, which materially improves the reliability of valid JSON
(and therefore Pydantic) validation for collection fields like ``hashtags``,
``thread`` and ``supporting_points``.  This is a minimal provider-specific
adaptation; schema validation stays owned by the generators' parser.
"""

from __future__ import annotations

from openai import OpenAI

from app.core.config import settings
from app.transformation.llm.provider import LLMProvider

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEFAULT_MODEL = "gemini-2.5-flash"

_UNSET = object()


def _normalize_gemini_base_url(base: str) -> str:
    """Return an OpenAI-compatible Gemini base URL.

    The OpenAI client needs the ``/v1beta/openai/`` chat path.  A user may
    configure either the full OpenAI-compatible URL or Google's native
    ``https://generativelanguage.googleapis.com/v1beta`` endpoint; in the latter
    case we deterministically append ``openai/`` so the OpenAI-compatible
    interface is used.
    """
    url = base.rstrip("/")
    if url.endswith("/openai") or url.endswith("/v1"):
        return url + "/"
    return url + "/openai/"


class GeminiLLMProvider(LLMProvider):
    """Generate text using Gemini through its OpenAI-compatible endpoint."""

    is_external: bool = True
    is_local: bool = False
    requires_network: bool = True
    supports_offline: bool = False

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = _UNSET,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._model = model or settings.LLM_MODEL or _DEFAULT_MODEL
        self._api_key = api_key or settings.LLM_API_KEY
        if base_url is _UNSET:
            base = settings.LLM_BASE_URL or _DEFAULT_BASE_URL
        elif base_url is None:
            base = _DEFAULT_BASE_URL
        else:
            base = base_url
        self._base_url = _normalize_gemini_base_url(base)
        self._temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self._max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS
        self._timeout = timeout if timeout is not None else settings.LLM_TIMEOUT_SECONDS
        # SDK-internal auto-retries are disabled by default so the application
        # ProviderManager stays the single retry owner (as it is for OpenAI).
        self._max_retries = (
            max_retries if max_retries is not None else settings.LLM_SDK_MAX_RETRIES
        )
        if not self._api_key:
            raise ValueError(
                "LLM_API_KEY is not configured. Set LLM_API_KEY in the environment "
                "(use a Gemini API key when LLM_PROVIDER=gemini) or use "
                "FakeLLMProvider for offline/tests."
            )
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        content = None
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            content = None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Gemini provider returned empty content.")
        return content.strip()
