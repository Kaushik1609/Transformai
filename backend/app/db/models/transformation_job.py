"""
TransformIQ Backend — TransformationJob ORM Model

Represents a single multi-output transformation request.
Jobs are queued to Redis and processed by the background worker (Phase 6+).
Phase 2 only creates and persists the record; no actual job is enqueued.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project
    from app.db.models.source import Source
    from app.db.models.generation_configuration import GenerationConfiguration
    from app.db.models.output import Output


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransformationJob(Base):
    """
    A single transformation request that may produce multiple output types.

    Status lifecycle:
        queued → running → completed | failed | cancelled

    Relationships:
        project:       N-1 → Project
        source:        N-1 → Source
        configuration: N-1 → GenerationConfiguration
        outputs:       1-N → Output
    """
    __tablename__ = "transformation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Source UUID. Nullable (Phase 15) to support prompt-only "
        "transformations with no source document.",
    )
    prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        doc="Operator prompt (Phase 15). Optional; at least one of source_id / "
        "prompt is required for a transformation job.",
    )
    configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_outputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="transformation_jobs",
    )
    source: Mapped["Source"] = relationship(
        "Source",
        back_populates="transformation_jobs",
    )
    configuration: Mapped["GenerationConfiguration"] = relationship(
        "GenerationConfiguration",
        back_populates="transformation_jobs",
    )
    outputs: Mapped[list["Output"]] = relationship(
        "Output",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<TransformationJob id={self.id!s} status={self.status!r}>"
