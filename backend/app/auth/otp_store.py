"""
TransformIQ Backend — OTP Store (Phase 11F)

Persists at most ONE active OTP record per (channel, identifier). Only the
HMAC-SHA256 digest of the code is stored — the raw code never touches the store.

Backends:
- ``MemoryOtpStore``: in-process dict. Default and used by tests/offline dev.
- ``RedisOtpStore``: shared Redis keys with TTL (production,
  OTP_STORE_BACKEND=redis).

The FastAPI dependency ``get_otp_store`` caches a store per app instance so
isolated test apps never share state.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import structlog
from fastapi import Request

from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class OtpRecord:
    """Single active OTP record. Raw code is never stored."""

    otp_hash: str
    issued_at: int
    expires_at: float
    attempts_remaining: int
    next_resend_at: float
    issue_count: int = 1
    created_at: float = 0.0
    used: bool = False

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = self.issued_at


class OtpStore(ABC):
    """Abstract store for OTP records keyed by (channel, identifier)."""

    @abstractmethod
    def get(self, channel: str, identifier: str) -> OtpRecord | None: ...

    @abstractmethod
    def put(self, channel: str, identifier: str, record: OtpRecord) -> None: ...

    @abstractmethod
    def delete(self, channel: str, identifier: str) -> None: ...


def _store_key(channel: str, identifier: str) -> str:
    return f"{channel}:{identifier.strip().lower()}"


class MemoryOtpStore(OtpStore):
    """In-process single-active OTP store with lazy expiry sweeping."""

    def __init__(self) -> None:
        self._records: dict[str, OtpRecord] = {}

    def get(self, channel: str, identifier: str) -> OtpRecord | None:
        key = _store_key(channel, identifier)
        record = self._records.get(key)
        if record is None:
            return None
        if record.used or time.time() > record.expires_at:
            self._records.pop(key, None)
            return None
        return record

    def put(self, channel: str, identifier: str, record: OtpRecord) -> None:
        # Single-active: any previous code for this (channel, identifier) is
        # invalidated by replacing it.
        self._records[_store_key(channel, identifier)] = record

    def delete(self, channel: str, identifier: str) -> None:
        self._records.pop(_store_key(channel, identifier), None)


class RedisOtpStore(OtpStore):
    """Redis-backed single-active OTP store (production)."""

    _TTL_MARGIN = 60

    def __init__(self, client=None) -> None:
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import redis

            self._client = redis.from_url(settings.REDIS_URL)
        return self._client

    def get(self, channel: str, identifier: str) -> OtpRecord | None:
        raw = self.client.get(f"otp:{_store_key(channel, identifier)}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        record = OtpRecord(
            otp_hash=str(data["otp_hash"]),
            issued_at=int(data["issued_at"]),
            expires_at=float(data["expires_at"]),
            attempts_remaining=int(data["attempts_remaining"]),
            next_resend_at=float(data["next_resend_at"]),
            issue_count=int(data.get("issue_count", 1)),
            created_at=float(data.get("created_at", data["issued_at"])),
            used=bool(data.get("used", False)),
        )
        if record.used or time.time() > record.expires_at:
            self.delete(channel, identifier)
            return None
        return record

    def put(self, channel: str, identifier: str, record: OtpRecord) -> None:
        payload = json.dumps(
            {
                "otp_hash": record.otp_hash,
                "issued_at": record.issued_at,
                "expires_at": record.expires_at,
                "attempts_remaining": record.attempts_remaining,
                "next_resend_at": record.next_resend_at,
                "issue_count": record.issue_count,
                "created_at": record.created_at,
                "used": record.used,
            }
        )
        ttl = int(record.expires_at - time.time()) + self._TTL_MARGIN
        self.client.set(f"otp:{_store_key(channel, identifier)}", payload, ex=max(ttl, 1))

    def delete(self, channel: str, identifier: str) -> None:
        self.client.delete(f"otp:{_store_key(channel, identifier)}")


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------

def build_otp_store():
    if settings.OTP_STORE_BACKEND == "redis":
        return RedisOtpStore()
    return MemoryOtpStore()


def get_otp_store(request: Request):
    """FastAPI dependency — one store per app instance, cached on app.state."""
    key = "transformiq_otp_store"
    store = getattr(request.app.state, key, None)
    if store is None:
        store = build_otp_store()
        setattr(request.app.state, key, store)
    return store