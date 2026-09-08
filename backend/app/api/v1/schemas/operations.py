"""Phase 12D-G — read-only Security Operations views (schemas).

These are OBSERVABILITY endpoints: they return bounded, already-redacted
operational events to the authenticated owner only. They never expose source
content, credentials, secrets, raw PII, or other users' events.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SecurityEventResponse(BaseModel):
    """One bounded security event (safe, redacted operational fields only)."""

    event_type: str
    outcome: str
    timestamp: str
    user_id: str | None = None
    project_id: str | None = None
    source_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SecurityEventListResponse(BaseModel):
    """Owner-scoped list of bounded security events."""

    success: bool = True
    count: int
    data: list[SecurityEventResponse] = Field(default_factory=list)


__all__ = [
    "SecurityEventListResponse",
    "SecurityEventResponse",
]