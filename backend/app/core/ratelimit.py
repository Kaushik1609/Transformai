"""
TransformIQ Backend — Rate Limiting (Phase 11F)

A small rate-limiter abstraction with two backends:

- ``MemoryRateLimiter``: sliding-window, in-process. Default and used by tests.
- ``RedisRateLimiter``: fixed-window INCR/EXPIRE sharing the existing Redis
  infrastructure (redis-py already in use for RQ jobs). Used in production
  when RATE_LIMIT_BACKEND=redis.

Each FastAPI app instance owns its own limiter (cached on ``app.state``),
so isolated test apps never accumulate counters across suites while the
production app keeps a single shared counter.

Dependency usage:
    from app.core.ratelimit import rate_limit_bucket
    from fastapi import Depends

    @router.post("")
    async def create(db=Depends(get_db), _: None = Depends(rate_limit_bucket("source_upload"))):
        ...
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass

import structlog
from fastapi import HTTPException, Request, status
from fastapi import Depends as FastAPIDepends

from app.core.config import settings
from app.core.audit import emit_security_event

logger = structlog.get_logger(__name__)

_BUCKET_SPEC = {
    "otp_request": ("RATE_LIMIT_OTP_REQUEST_MAX", "RATE_LIMIT_OTP_REQUEST_WINDOW"),
    "otp_verify": ("RATE_LIMIT_OTP_VERIFY_MAX", "RATE_LIMIT_OTP_VERIFY_WINDOW"),
    "login": ("RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW"),
    "source_upload": ("RATE_LIMIT_SOURCE_UPLOAD_MAX", "RATE_LIMIT_SOURCE_UPLOAD_WINDOW"),
    "transformation": ("RATE_LIMIT_TRANSFORMATION_MAX", "RATE_LIMIT_TRANSFORMATION_WINDOW"),
}


@dataclass(frozen=True)
class RateLimitStatus:
    """Result of a rate-limit check."""

    allowed: bool
    limit: int
    retry_after: float


class RateLimiter(ABC):
    """Abstract rate-limiting primitive."""

    @abstractmethod
    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> RateLimitStatus:
        """Record one hit for ``key`` in ``bucket`` and report allowance."""


class MemoryRateLimiter(RateLimiter):
    """Sliding-window in-process limiter (tests, offline development)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> RateLimitStatus:
        now = time.monotonic()
        hits = self._hits[(bucket, key)]
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            retry = (hits[0] + window_seconds) - now if hits else 0.0
            return RateLimitStatus(allowed=False, limit=limit, retry_after=max(retry, 1.0))
        hits.append(now)
        return RateLimitStatus(allowed=True, limit=limit, retry_after=0.0)


class RedisRateLimiter(RateLimiter):
    """Fixed-window limiter backed by the existing Redis instance."""

    def __init__(self, client=None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import redis

            self._client = redis.from_url(settings.REDIS_URL)
        return self._client

    def hit(self, bucket: str, key: str, limit: int, window_seconds: int) -> RateLimitStatus:
        rkey = f"rl:{bucket}:{key}"
        try:
            current = self.client.incr(rkey)
            if current > limit:
                ttl = self.client.ttl(rkey)
                retry = ttl if ttl > 0 else window_seconds
                return RateLimitStatus(allowed=False, limit=limit, retry_after=float(retry))
            if current == 1:
                self.client.expire(rkey, window_seconds)
            return RateLimitStatus(allowed=True, limit=limit, retry_after=0.0)
        except Exception:  # pragma: no cover - defensive fail-open on Redis outage
            logger.warning("redis_rate_limit_unavailable_failing_open", bucket=bucket)
            return RateLimitStatus(allowed=True, limit=limit, retry_after=0.0)


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------

def build_rate_limiter() -> RateLimiter:
    if settings.RATE_LIMIT_BACKEND == "redis":
        return RedisRateLimiter()
    return MemoryRateLimiter()


def get_rate_limiter(request: Request) -> RateLimiter:
    """FastAPI dependency — one limiter per app instance, cached on app.state."""
    key = "transformiq_rate_limiter"
    limiter = getattr(request.app.state, key, None)
    if limiter is None:
        limiter = build_rate_limiter()
        setattr(request.app.state, key, limiter)
    return limiter


def get_rate_limit_spec(bucket: str) -> tuple[int, int]:
    """Return (limit, window_seconds) for a bucket, reading settings live."""
    if bucket not in _BUCKET_SPEC:
        raise KeyError(f"Unknown rate-limit bucket: {bucket}")
    limit_attr, window_attr = _BUCKET_SPEC[bucket]
    limit = getattr(settings, limit_attr)
    window = getattr(settings, window_attr)
    return int(limit), int(window)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_bucket(bucket: str):
    """Factory producing a FastAPI dependency that applies a configured bucket."""

    async def _dependency(
        request: Request,
        limiter: RateLimiter = FastAPIDepends(get_rate_limiter),
    ) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit, window = get_rate_limit_spec(bucket)
        status_result = limiter.hit(bucket, _client_ip(request), limit, window)
        if not status_result.allowed:
            emit_security_event(
                "rate_limit_triggered",
                outcome="denied",
                reason=(
                    f"Rate limit exceeded for '{bucket}'"
                ),
                details={
                    "bucket": bucket,
                    "limit": limit,
                    "retry_after_seconds": int(status_result.retry_after),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for '{bucket}'. Try again after "
                       f"{int(status_result.retry_after)} seconds.",
                headers={"Retry-After": str(max(1, int(status_result.retry_after)))},
            )

    return _dependency