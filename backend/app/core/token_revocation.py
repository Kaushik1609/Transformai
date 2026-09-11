"""
TransformIQ Backend — Server-Side Token Revocation (Phase 13A)

Every access token carries a unique ``jti`` claim. ``logout`` registers that
``jti`` in a revocation store so the token cannot be replayed afterwards:

- ``MemoryTokenRevocationStore``: bounded in-process denylist of
  ``{jti: expires_at}`` entries. Expired entries are swept lazily on access and
  the store enforces ``AUTH_REVOKED_TOKEN_MAX`` (oldest entries evicted). This
  is the single-replica default and the test/offline backend.
- ``RedisTokenRevocationStore``: shared denylist across replicas. Each revoked
  ``jti`` is stored with a TTL equal to the remainder of the token's life, so
  entries expire naturally. Checks fail open on a Redis outage (revocation is a
  defense-in-depth layer; the short-lived token still expires on its own).

Only the opaque ``jti`` (never the token itself, user, or expiry) is stored.
The store never logs or exposes the revoked identifiers.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import datetime, timezone

import structlog
from fastapi import Request

from app.core.config import settings

logger = structlog.get_logger(__name__)


class TokenRevocationStore(ABC):
    """Abstract revocation store keyed by a token's ``jti`` claim."""

    @abstractmethod
    def revoke(self, jti: str, expires_at: datetime | None = None) -> bool:
        """Register ``jti`` as revoked until (at most) ``expires_at``."""

    @abstractmethod
    def is_revoked(self, jti: str) -> bool:
        """Return True when ``jti`` has been revoked."""


class MemoryTokenRevocationStore(TokenRevocationStore):
    """Bounded, expiry-aware in-process denylist.

    Entries are stored in insertion order so the eldest (which is also the
    least recently added) is evicted first once ``AUTH_REVOKED_TOKEN_MAX`` is
    reached. Expired entries are swept before every access to keep lookups
    accurate without a background task.
    """

    def __init__(self, max_entries: int | None = None) -> None:
        self._max_entries = max(
            1, max_entries or settings.AUTH_REVOKED_TOKEN_MAX
        )
        self._revoked: OrderedDict[str, float] = OrderedDict()

    def _sweep(self) -> None:
        now = time.time()
        expired = [
            jti
            for jti, expires_at in self._revoked.items()
            if expires_at is not None and expires_at <= now
        ]
        for jti in expired:
            self._revoked.pop(jti, None)

    def revoke(self, jti: str, expires_at: datetime | None = None) -> bool:
        if not jti:
            return False
        deadline = (
            expires_at.timestamp()
            if expires_at is not None
            else float("inf")
        )
        self._revoked[jti] = deadline
        if len(self._revoked) > self._max_entries:
            while len(self._revoked) > self._max_entries:
                _, oldest = self._revoked.popitem(last=False)
                if oldest == float("inf"):
                    break
        return True

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        self._sweep()
        return jti in self._revoked

    def __len__(self) -> int:
        return len(self._revoked)


class RedisTokenRevocationStore(TokenRevocationStore):
    """Shared denylist backed by the existing Redis infrastructure."""

    _KEY_PREFIX = "authn:revoked:"

    def __init__(self, client=None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import redis

            self._client = redis.from_url(settings.REDIS_URL)
        return self._client

    def revoke(self, jti: str, expires_at: datetime | None = None) -> bool:
        if not jti:
            return False
        rkey = f"{self._KEY_PREFIX}{jti}"
        try:
            if expires_at is not None:
                ttl = (expires_at - datetime.now(timezone.utc)).total_seconds()
            else:
                ttl = settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            if ttl > 0:
                self.client.set(rkey, "1", ex=int(ttl))
            else:
                self.client.delete(rkey)
            return True
        except Exception:  # pragma: no cover - Redis outage path
            logger.warning("token_revocation_redis_unavailable")
            return False

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        try:
            return bool(self.client.exists(f"{self._KEY_PREFIX}{jti}"))
        except Exception:  # pragma: no cover - Redis outage path (fail open)
            logger.warning("token_revocation_check_redis_unavailable")
            return False


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

_SINGLETON: TokenRevocationStore | None = None


def build_revocation_store() -> TokenRevocationStore:
    if settings.AUTH_TOKEN_REVOCATION_STORE == "redis":
        return RedisTokenRevocationStore()
    return MemoryTokenRevocationStore()


def get_revocation_store(
    request: Request = None,
) -> TokenRevocationStore:
    """FastAPI dependency — one store per app instance, cached on app.state.

    Mirrors the rate-limiter caching pattern so isolated test apps never share
    revocation state across suites while the production app keeps a single
    shared in-process store (or a Redis-backed store).
    """
    global _SINGLETON
    if request is not None:
        key = "transformiq_token_revocation_store"
        store = getattr(request.app.state, key, None)
        if store is None:
            store = build_revocation_store()
            setattr(request.app.state, key, store)
        return store
    if _SINGLETON is None:
        _SINGLETON = build_revocation_store()
    return _SINGLETON


def revoke_access_token(
    token: str,
    store: TokenRevocationStore | None = None,
) -> bool:
    """Decode ``token`` and revoke its ``jti`` (idempotent, best-effort).

    A token without a ``jti`` (pre-Phase 13A) or un-decodable token cannot be
    revoked and returns False — logout still succeeds (client discards the
    token) and the short-lived token expires on its own.
    """
    from app.core.security import decode_access_token

    try:
        payload = decode_access_token(token)
    except ValueError:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    if store is None:
        store = get_revocation_store()
    expires_at = None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        expires_at = datetime.fromtimestamp(float(exp), tz=timezone.utc)
    return store.revoke(str(jti), expires_at)


__all__ = [
    "TokenRevocationStore",
    "MemoryTokenRevocationStore",
    "RedisTokenRevocationStore",
    "build_revocation_store",
    "get_revocation_store",
    "revoke_access_token",
]