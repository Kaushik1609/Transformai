"""
TransformIQ Backend — GenerationConfiguration ORM Model

Stores per-project user configuration that controls how content is generated.
A project may have multiple saved configurations.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project
    from app.db.models.transformation_job import TransformationJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationConfiguration(Base):
    """
    User-supplied generation parameters for a transformation job.

    Relationships:
        project:             N-1 → Project
        transformation_jobs: 1-N → TransformationJob
    """
    __tablename__ = "generation_configurations"

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
    target_audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="English",
    )
    detail_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    communication_objective: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    content_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="generation_configurations",
    )
    transformation_jobs: Mapped[list["TransformationJob"]] = relationship(
        "TransformationJob",
        back_populates="configuration",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<GenerationConfiguration id={self.id!s} project_id={self.project_id!s}>"
