"""
TransformIQ Backend — Output ORM Model

Represents a single generated content output from a transformation job.
One job may produce multiple outputs (summary, linkedin, presentation, etc.).
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.transformation_job import TransformationJob
    from app.db.models.verification_result import VerificationResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Output(Base):
    """
    A generated content artifact produced by a transformation job.

    output_type values:
        summary | linkedin | x | advisory | infographic | presentation | video

    Status lifecycle:
        generating → completed | failed

    Relationships:
        job:                  N-1 → TransformationJob
        verification_results: 1-N → VerificationResult
    """
    __tablename__ = "outputs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transformation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    output_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="generating",
        index=True,
    )
    structured_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    job: Mapped["TransformationJob"] = relationship(
        "TransformationJob",
        back_populates="outputs",
    )
    verification_results: Mapped[list["VerificationResult"]] = relationship(
        "VerificationResult",
        back_populates="output",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Output id={self.id!s} type={self.output_type!r} status={self.status!r}>"
