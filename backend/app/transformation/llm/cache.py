"""Phase 11L-A — LLM output caching wrapper.

``CachingLLMProvider`` transparently wraps any ``LLMProvider`` (proxy interface
via ``__getattr__`` so the Phase 11D ``last_metadata`` and generator contract
keep working) and serves deterministic, successful generation results from the
configured cache backend.

Cache key construction (transformative hash, no plaintext prompt stored):
  SHA-256 of canonical JSON::

    {"v": key_version, "scope": project_id, "provider": provider,
     "model": model, "system": sha256(system_prompt),
     "user": sha256(user_content)}

The ``scope`` is bound to ``job.project_id`` at wrap time so cached results can
never leak across tenant boundaries even though prompts are not directly read.

Only successful generations are cached. Cache backend errors are fail-open:
the provider is called and the error is observable via the
``llm_cache_errors_total`` metric — caching can never block or corrupt a job.
"""

from __future__ import annotations

import hashlib
import json
import time

from app.core.metrics import metrics
from app.transformation.llm.provider import LLMProvider


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_cache_key(
    *,
    scope: str,
    provider: str,
    model: str,
    system_prompt: str,
    user_content: str,
    key_version: str,
) -> str:
    """Return the deterministic SHA-256 cache key for one LLM call."""
    canonical = {
        "v": key_version,
        "scope": str(scope or ""),
        "provider": provider,
        "model": model,
        "system": _sha256_hex(system_prompt),
        "user": _sha256_hex(user_content),
    }
    return _sha256_hex(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


class CachingLLMProvider(LLMProvider):
    """Wrap an LLM provider so successful calls are cached per project scope."""

    def __init__(
        self,
        provider: LLMProvider,
        backend,
        *,
        scope: str = "",
        ttl_seconds: int = 3600,
        key_version: str = "v1",
        provider_name: str | None = None,
        model: str | None = None,
        enabled: bool = True,
    ) -> None:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer.")
        self._provider = provider
        self._backend = backend
        self._scope = str(scope or "")
        self._ttl_seconds = ttl_seconds
        self._key_version = key_version or "v1"
        self._provider_name = provider_name or getattr(
            provider, "provider_name", None
        ) or "unknown"
        self._model = model or getattr(provider, "model", None) or ""
        self._enabled = bool(enabled)

    # -- proxy interface ----------------------------------------------------

    def __getattr__(self, name: str):  # pragma: no cover - trivial delegation
        return getattr(self._provider, name)

    # -- generation ---------------------------------------------------------

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        if not self._enabled:
            return self._provider.generate_text(
                system_prompt=system_prompt, user_content=user_content
            )

        key = build_cache_key(
            scope=self._scope,
            provider=self._provider_name,
            model=self._model,
            system_prompt=system_prompt,
            user_content=user_content,
            key_version=self._key_version,
        )

        cached = self._read(key)
        if cached is not None:
            metrics.inc("llm_cache_hits_total", {"provider": self._provider_name})
            return cached

        metrics.inc("llm_cache_misses_total", {"provider": self._provider_name})
        result = self._provider.generate_text(
            system_prompt=system_prompt, user_content=user_content
        )
        self._write(key, result)
        return result

    # -- helpers ------------------------------------------------------------

    def _read(self, key: str) -> str | None:
        try:
            raw = self._backend.get(key)
        except Exception:  # pragma: no cover - defensive (backends are fail-open)
            raw = None
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):  # pragma: no cover
            return None

    def _write(self, key: str, value: str) -> None:
        try:
            self._backend.set(key, value.encode("utf-8"), self._ttl_seconds)
        except Exception:  # pragma: no cover - defensive (backends are fail-open)
            metrics.inc("llm_cache_errors_total", {"provider": self._provider_name})


__all__ = ["CachingLLMProvider", "build_cache_key", "LLMProvider"]