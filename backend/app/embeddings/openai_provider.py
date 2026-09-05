"""OpenAI-backed embedding provider wired through the existing EMBEDDING_* settings.

Produces real 1536-dimensional vectors (text-embedding-3-small by default)
compatible with the ``source_chunks.embedding`` pgvector column. The API key is
consumed from configuration only and is never exposed to callers or logged.
Source text is never included in log output and is never silently truncated
before submission.

The underlying OpenAI SDK client is injectable so tests can exercise response
parsing and dimensionality validation without any network or real credentials.
"""

from __future__ import annotations

import openai

from app.core.config import settings
from app.embeddings.base import EmbeddingProvider

_UNSET = object()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embed text batches using an OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = _UNSET,
        dimensions: int | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        client=None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.EMBEDDING_API_KEY
        self._model = model or settings.EMBEDDING_MODEL
        self._base_url = settings.EMBEDDING_BASE_URL if base_url is _UNSET else base_url
        self._dimensions = dimensions if dimensions is not None else settings.EMBEDDING_DIMENSIONS
        self._timeout = timeout if timeout is not None else settings.EMBEDDING_TIMEOUT_SECONDS
        # SDK-level auto-retries are DISABLED (EMBEDDING_SDK_MAX_RETRIES defaults
        # to 0): the application EmbeddingResilientProvider is the single retry
        # owner and EMBEDDING_MAX_TOTAL_ATTEMPTS is the only ceiling, so SDK and
        # app-layer retries never amplify each other.
        self._max_retries = max_retries if max_retries is not None else settings.EMBEDDING_SDK_MAX_RETRIES
        if not self._api_key:
            raise ValueError(
                "EMBEDDING_API_KEY is not configured. Set EMBEDDING_API_KEY in the "
                "environment or use FakeEmbeddingProvider for offline/tests."
            )
        self._client = client if client is not None else self._build_client()
        if self._client is None:
            raise ValueError("Embedding client could not be created.")

    def _build_client(self):
        client_kwargs: dict = {
            "api_key": self._api_key,
            "timeout": self._timeout,
            "max_retries": self._max_retries,
        }
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        return openai.OpenAI(**client_kwargs)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one validated embedding vector per input text."""
        if not isinstance(texts, list):
            raise ValueError("Embedding input must be a list of strings.")
        if any(not isinstance(text, str) for text in texts):
            raise ValueError("Embedding input items must all be strings.")

        response = self._client.embeddings.create(model=self._model, input=list(texts))
        data = getattr(response, "data", None)
        if data is None or len(data) != len(texts):
            returned = len(data) if data is not None else 0
            raise ValueError(
                f"Embedding provider returned {returned} vectors for {len(texts)} texts."
            )

        ordered = sorted(data, key=lambda item: getattr(item, "index", 0))
        vectors: list[list[float]] = []
        for item in ordered:
            embedding = getattr(item, "embedding", None)
            if not isinstance(embedding, (list, tuple)):
                raise ValueError("Embedding response entry is missing a numeric vector.")
            vector = [float(value) for value in embedding]
            if len(vector) != self._dimensions:
                raise ValueError(
                    f"Embedding dimensions mismatch: expected {self._dimensions}, "
                    f"got {len(vector)}."
                )
            vectors.append(vector)
        return vectors