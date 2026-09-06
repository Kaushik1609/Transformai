"""
TransformIQ Backend — Structured Security / Audit Events (Phase 11K)

A lightweight, in-process security-event emitter.  Every event carries only
non-secret identifiers plus an ``event_type`` and ``outcome``; values are
routed through ``redact_secrets`` before being logged so a logging regression
cannot leak credentials or PII.

Two sinks, both gated by ``settings.SECURITY_AUDIT_ENABLED``:

- a structlog ``security_event`` record (the durable, aggregated sink).
- a bounded in-process list inspected by tests (``security_events()``).

Events describe *what happened* (safe identifiers + outcome + reason).  Raw
bodies, tokens, passwords and document content must never be attached here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.core.redaction import _redact_value

logger = structlog.get_logger(__name__)

# Max in-process events retained for inspection (bounded memory).
_MAX_SINK_SIZE = 5000

_EVENTS: list[dict[str, Any]] = []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SecurityEvent:
    """Safe, serializable description of one security-relevant occurrence."""

    event_type: str
    outcome: str = "observed"
    timestamp: datetime = field(default_factory=_utcnow)
    user_id: str | None = None
    project_id: str | None = None
    source_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def emit_security_event(
    event_type: str,
    *,
    outcome: str = "observed",
    user_id: str | None = None,
    project_id: str | None = None,
    source_id: str | None = None,
    job_id: str | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> SecurityEvent | None:
    """Record one security event (skipped entirely when auditing is disabled).

    Only non-secret identifiers and a short reason are stored.  ``details`` is
    redacted as a safety net before logging.  Returns the event or None when
    ``SECURITY_AUDIT_ENABLED`` is false.
    """
    if not settings.SECURITY_AUDIT_ENABLED:
        return None

    event = SecurityEvent(
        event_type=event_type,
        outcome=outcome,
        user_id=str(user_id) if user_id is not None else None,
        project_id=str(project_id) if project_id is not None else None,
        source_id=str(source_id) if source_id is not None else None,
        job_id=str(job_id) if job_id is not None else None,
        reason=reason,
        details=details or {},
    )

    # Deterministic ordering for inspection.
    record = {
        "event_type": event.event_type,
        "outcome": event.outcome,
        "timestamp": event.timestamp.isoformat(),
        "user_id": event.user_id,
        "project_id": event.project_id,
        "source_id": event.source_id,
        "job_id": event.job_id,
        "reason": event.reason,
    }
    record.update({k: _redact_value(v) for k, v in event.details.items()})

    _EVENTS.append(record)
    if len(_EVENTS) > _MAX_SINK_SIZE:
        _EVENTS.pop(0)

    logger.info("security_event", **record)
    return event


def security_events() -> list[dict[str, Any]]:
    """Return a copy of the in-process security events (test inspection)."""
    return list(_EVENTS)


def clear_security_events() -> None:
    """Reset the in-process security event list (isolated tests)."""
    _EVENTS.clear()


__all__ = [
    "SecurityEvent",
    "emit_security_event",
    "security_events",
    "clear_security_events",
]