"""Build an embedding provider from application settings.

Parallel to ``app.transformation.llm.factory`` but fully decoupled from the LLM
provider layer. The default provider is "fake" (deterministic, offline, no
credentials required). When "openai" is selected, an ``OpenAIEmbeddingProvider``
is constructed and wrapped in an ``EmbeddingResilientProvider`` so timeouts,
retries, Retry-After handling and circuit breaking are applied centrally.

Failure semantics (11G-E): an explicitly selected real provider NEVER falls back
to fake embeddings. If ``EMBEDDING_PROVIDER=openai`` without an API key the
factory raises a clear ``ValueError`` at construction time so the failure is
explicit instead of silently degrading RAG quality.
"""

from __future__ import annotations

from app.core.config import settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.embeddings.resilience import EmbeddingResilientProvider

SUPPORTED_EMBEDDING_PROVIDERS = ("fake", "openai")


def build_embedding_provider(
    provider: str | None = None, *, dimensions: int | None = None
) -> EmbeddingProvider:
    """Return an embedding provider instance based on settings.

    Args:
        provider: Explicit provider name override (defaults to EMBEDDING_PROVIDER).
        dimensions: Vector dimensionality (defaults to EMBEDDING_DIMENSIONS).

    Raises:
        ValueError: For an unknown provider name, or an explicitly selected
            real provider that cannot be constructed (e.g. missing API key).
    """
    name = (provider or settings.EMBEDDING_PROVIDER or "fake").strip().lower()
    resolved_dimensions = dimensions if dimensions is not None else settings.EMBEDDING_DIMENSIONS

    if name == "fake":
        return FakeEmbeddingProvider(dimensions=resolved_dimensions)
    if name == "openai":
        base = OpenAIEmbeddingProvider(dimensions=resolved_dimensions)
        return EmbeddingResilientProvider(
            base,
            max_attempts=settings.EMBEDDING_MAX_RETRIES + 1,
        )
    raise ValueError(f"Unsupported embedding provider: {name!r}")


def build_resilient_embedding_provider(
    provider: EmbeddingProvider | None = None, *, max_attempts: int | None = None
) -> EmbeddingProvider:
    """Wrap an injected provider (or the configured default) in resilience.

    Used by the worker to guarantee all embedding providers benefit from
    bounded retries/backoff regardless of how the provider was constructed.
    """
    base = provider if provider is not None else build_embedding_provider()
    if isinstance(base, (FakeEmbeddingProvider, EmbeddingResilientProvider)):
        return base
    return EmbeddingResilientProvider(
        base,
        max_attempts=max_attempts if max_attempts is not None else settings.EMBEDDING_MAX_RETRIES + 1,
    )