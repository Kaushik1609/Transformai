"""
TransformIQ Backend — SecurityEventRecord ORM Model (Phase 13D)

Durable copy of the in-process security-event stream (``app.core.audit``).
Only safe, already-redacted operational fields are stored: event type, outcome,
timestamps and non-secret identifiers plus a ``details`` JSON object. Never
store tokens, credentials, raw PII, or source content here.

Store intentionally references entities as plain strings (no foreign keys) so a
record survives even if the owning project/source/user is deleted.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SecurityEventRecord(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(80), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "ix_security_events_owner_lookup",
            "project_id",
            "user_id",
            "occurred_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<SecurityEventRecord id={self.id!s} event={self.event_type!r}>"