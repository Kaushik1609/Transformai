"""Canonical, source-grounded content aggregate for Phase 4."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project
    from app.db.models.source import Source
    from app.db.models.content_analysis_trace import ContentAnalysisTrace


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CanonicalContent(Base):
    __tablename__ = "canonical_contents"
    __table_args__ = (UniqueConstraint("source_id", name="uq_canonical_contents_source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    entities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    key_points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    claims: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    statistics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    dates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_references: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped["Source"] = relationship("Source", back_populates="canonical_content")
    project: Mapped["Project"] = relationship("Project")
    traces: Mapped[list["ContentAnalysisTrace"]] = relationship(
        "ContentAnalysisTrace", back_populates="canonical_content", cascade="all, delete-orphan", lazy="selectin"
    )
