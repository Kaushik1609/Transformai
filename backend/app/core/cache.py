"""TransformIQ — cache backends (Phase 11L-A).

A small abstraction over cache storage used by the LLM output cache. Two
backends mirror the existing rate-limiter convention:

  * ``MemoryCacheBackend`` — bounded in-process cache (default; offline/tests).
  * ``RedisCacheBackend`` — TTL cache on the shared Redis instance (production).

Both backends are fail-open: a cache read/write error is swallowed and logged
so cached data can never block or corrupt job execution. Redis being down means
the cache simply produces misses and the underlying provider is called.
"""

from __future__ import annotations

import structlog
import redis

from app.core.config import settings

logger = structlog.get_logger(__name__)


class CacheBackend:
    """Abstract cache backend (bytes in, bytes out)."""

    def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        raise NotImplementedError


class MemoryCacheBackend(CacheBackend):
    """Bounded in-process TTL cache (deterministic, offline, thread-safe)."""

    def __init__(self, max_entries: int = 10_000) -> None:
        import threading
        from collections import OrderedDict

        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer.")
        self._max_entries = max_entries
        self._entries: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()
        self._lock = threading.RLock()
        self._time = __import__("time").time

    def get(self, key: str) -> bytes | None:
        if not isinstance(key, str) or not key:
            raise ValueError("Cache key must be a non-empty string.")
        now = self._time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Cache key must be a non-empty string.")
        if not isinstance(value, bytes):
            raise ValueError("Cache value must be bytes.")
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer.")
        now = self._time()
        with self._lock:
            self._entries[key] = (now + float(ttl_seconds), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class RedisCacheBackend(CacheBackend):
    """TTL cache backed by the shared Redis instance (production)."""

    def __init__(
        self,
        client=None,
        prefix: str = "transformiq:cache:",
        *,
        url: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._client = client
        self._url = url

    @property
    def client(self):
        if self._client is None:
            self._client = redis.from_url(self._url or settings.REDIS_URL)
        return self._client

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> bytes | None:
        if not isinstance(key, str) or not key:
            raise ValueError("Cache key must be a non-empty string.")
        try:
            value = self.client.get(self._key(key))
            return bytes(value) if value is not None else None
        except Exception as exc:  # pragma: no cover - Redis outage path
            logger.warning(
                "cache_get_unavailable_failing_open",
                error_type=type(exc).__name__,
            )
            return None

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Cache key must be a non-empty string.")
        if not isinstance(value, bytes):
            raise ValueError("Cache value must be bytes.")
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer.")
        try:
            self.client.set(self._key(key), value, ex=ttl_seconds)
        except Exception as exc:  # pragma: no cover - Redis outage path
            logger.warning(
                "cache_set_unavailable_failing_open",
                error_type=type(exc).__name__,
            )


def build_cache_backend(backend: str | None = None) -> CacheBackend:
    """Build the configured cache backend (memory default, redis for prod)."""
    name = (backend or settings.CACHE_BACKEND or "memory").strip().lower()
    if name == "memory":
        return MemoryCacheBackend()
    if name == "redis":
        return RedisCacheBackend()
    raise ValueError(f"Unsupported cache backend: {name!r}")