"""
TransformIQ Backend — Structured Security / Audit Events (Phase 11K/13D)

A lightweight security-event emitter.  Every event carries only non-secret
identifiers plus an ``event_type`` and ``outcome``; values are routed through
``redact_secrets`` before being stored/logged so a logging regression cannot
leak credentials or PII.

Three sinks, all gated by ``settings.SECURITY_AUDIT_ENABLED``:

- a structlog ``security_event`` record (the durable, aggregated sink).
- a bounded in-process list inspected by tests (``security_events()``).
- when ``SECURITY_AUDIT_SINK=database`` (Phase 13D), a bounded pending queue
  drained into the ``security_events`` table by request sessions
  (``drain_pending_audit_events``) or directly by workers
  (``persist_security_event_sync``). The security-events API then reads from
  the database instead of the in-process list.

Events describe *what happened* (safe identifiers + outcome + reason).  Raw
bodies, tokens, passwords and document content must never be attached here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import settings
from app.core.metrics import metrics
from app.core.redaction import _redact_value

logger = structlog.get_logger(__name__)

# Bounded in-process event retention (bounded memory).
_EVENTS: deque[dict[str, Any]] = deque()
# Bounded pending queue drained into the DB when SECURITY_AUDIT_SINK=database.
_PENDING_DB: deque[dict[str, Any]] = deque()
_MAX_PENDING = 2000

# Base keys stored verbatim; everything else in a record is a redacted detail.
_BASE_KEYS = frozenset(
    {
        "event_type",
        "outcome",
        "timestamp",
        "user_id",
        "project_id",
        "source_id",
        "job_id",
        "reason",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _memory_cap() -> int:
    return settings.SECURITY_AUDIT_MEMORY_MAX_EVENTS


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
    redacted as a safety net before logging/persistence. Returns the event or
    None when ``SECURITY_AUDIT_ENABLED`` is false.
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

    record = flat_record(event)

    _EVENTS.append(record)
    if len(_EVENTS) > _memory_cap():
        metrics.inc("security_events_drop_total", {"reason": "memory_cap"})
        _EVENTS.popleft()

    if settings.SECURITY_AUDIT_SINK == "database":
        _PENDING_DB.append(record)
        if len(_PENDING_DB) > _MAX_PENDING:
            metrics.inc("security_events_drop_total", {"reason": "db_pending_cap"})
            _PENDING_DB.popleft()

    logger.info("security_event", **record)
    return event


def flat_record(event: SecurityEvent) -> dict[str, Any]:
    """Deterministic flat dict (base keys verbatim, details flattened/redacted)."""
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
    return record


# ---------------------------------------------------------------------------
# Phase 13D — durable database sink
# ---------------------------------------------------------------------------


def _details_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in _BASE_KEYS}


def _row_to_record(row) -> dict[str, Any]:
    """Map an ORM ``SecurityEventRecord`` back to the flat audit-record shape."""
    details = dict(row.details or {})
    record = {
        "event_type": row.event_type,
        "outcome": row.outcome,
        "timestamp": (
            row.occurred_at.isoformat()
            if row.occurred_at is not None
            else None
        ),
        "user_id": row.user_id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "job_id": row.job_id,
        "reason": row.reason,
    }
    record.update(details)
    return record


async def drain_pending_audit_events(db) -> int:
    """Insert pending DB-sink events using ``db`` (the request session).

    Called at the end of a successful request (see ``app.db.session.get_db``)
    and by tests. Never raises: a persistence failure is logged and counted on
    ``security_events_drop_total{reason=db_write_error}`` but must not break
    the request that generated the events. Does not commit (the caller owns the
    transaction).
    """
    if not _PENDING_DB:
        return 0
    from app.db.models.security_event import SecurityEventRecord

    written = 0
    while _PENDING_DB:
        record = _PENDING_DB.popleft()
        try:
            db.add(
                SecurityEventRecord(
                    event_type=record.get("event_type") or "unknown",
                    outcome=record.get("outcome") or "observed",
                    occurred_at=_parse_timestamp(record.get("timestamp")),
                    user_id=record.get("user_id"),
                    project_id=record.get("project_id"),
                    source_id=record.get("source_id"),
                    job_id=record.get("job_id"),
                    reason=record.get("reason"),
                    details=_details_from_record(record),
                )
            )
            written += 1
        except Exception as exc:  # defensive: never break a request for audit
            metrics.inc("security_events_drop_total", {"reason": "db_write_error"})
            logger.warning(
                "audit_persist_row_failed",
                error=type(exc).__name__,
            )
    if written:
        metrics.inc("security_events_persisted_total", amount=written)
    return written


def persist_security_event_sync(db, record: dict[str, Any]) -> bool:
    """Insert a single already-redacted record synchronously (worker context).

    Used by the RQ worker where only a sync session is available. Best-effort:
    failures are logged and counted on ``security_events_drop_total``; the
    caller's transaction is left intact. Does not commit.
    """
    if not settings.SECURITY_AUDIT_ENABLED:
        return False
    if settings.SECURITY_AUDIT_SINK != "database":
        return False
    from app.db.models.security_event import SecurityEventRecord

    try:
        db.add(
            SecurityEventRecord(
                event_type=record.get("event_type") or "unknown",
                outcome=record.get("outcome") or "observed",
                occurred_at=_parse_timestamp(record.get("timestamp")),
                user_id=record.get("user_id"),
                project_id=record.get("project_id"),
                source_id=record.get("source_id"),
                job_id=record.get("job_id"),
                reason=record.get("reason"),
                details=_details_from_record(record),
            )
        )
        metrics.inc("security_events_persisted_total")
        return True
    except Exception as exc:  # defensive
        metrics.inc("security_events_drop_total", {"reason": "db_write_error"})
        logger.warning(
            "audit_persist_sync_failed",
            error=type(exc).__name__,
        )
        return False


def flush_pending_audit_sync(db) -> int:
    """Synchronously drain the pending DB-sink queue (worker context).

    Equivalent to ``drain_pending_audit_events`` for sync sessions. Used by RQ
    workers where only ``sqlalchemy.orm.Session`` is available. Never raises;
    does not commit.
    """
    if not _PENDING_DB:
        return 0
    from app.db.models.security_event import SecurityEventRecord

    written = 0
    while _PENDING_DB:
        record = _PENDING_DB.popleft()
        try:
            db.add(
                SecurityEventRecord(
                    event_type=record.get("event_type") or "unknown",
                    outcome=record.get("outcome") or "observed",
                    occurred_at=_parse_timestamp(record.get("timestamp")),
                    user_id=record.get("user_id"),
                    project_id=record.get("project_id"),
                    source_id=record.get("source_id"),
                    job_id=record.get("job_id"),
                    reason=record.get("reason"),
                    details=_details_from_record(record),
                )
            )
            written += 1
        except Exception as exc:  # defensive: never break a job for audit
            metrics.inc("security_events_drop_total", {"reason": "db_write_error"})
            logger.warning(
                "audit_persist_sync_flush_failed",
                error=type(exc).__name__,
            )
    if written:
        metrics.inc("security_events_persisted_total", amount=written)
    return written


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return _utcnow()


async def list_db_security_events(
    db,
    *,
    owned_projects: set[str],
    me: str,
    project_id: str | None = None,
    event_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Owner-scoped DB read used by the security-events API (Phase 13D).

    A user may see events they initiated (``user_id``) or that belong to
    projects they own.  Platform-global events are never exposed.  Filtering and
    counting mirror the in-memory implementation's contract.
    """
    from sqlalchemy import or_, select
    from app.db.models.security_event import SecurityEventRecord

    clauses = or_(
        SecurityEventRecord.user_id == me,
        SecurityEventRecord.project_id.in_(owned_projects or {""}),
    )
    if project_id is not None:
        clauses = SecurityEventRecord.project_id == project_id
    if event_type is not None:
        clauses = clauses & (SecurityEventRecord.event_type == event_type)

    rows = await db.scalars(
        select(SecurityEventRecord)
        .where(clauses)
        .order_by(SecurityEventRecord.occurred_at.desc())
        .limit(max(1, min(int(limit), 500)))
    )
    return [_row_to_record(row) for row in rows.all()]


def security_events() -> list[dict[str, Any]]:
    """Return a copy of the in-process security events (test inspection)."""
    import copy

    return copy.deepcopy(list(_EVENTS))


def clear_security_events() -> None:
    """Reset the in-process security event stores (isolated tests)."""
    _EVENTS.clear()
    _PENDING_DB.clear()


__all__ = [
    "SecurityEvent",
    "emit_security_event",
    "security_events",
    "clear_security_events",
    "drain_pending_audit_events",
    "persist_security_event_sync",
    "flush_pending_audit_sync",
    "list_db_security_events",
    "flat_record",
]