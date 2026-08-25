"""
TransformIQ Backend — Source ORM Model

Represents uploaded or directly-submitted source material.
For Phase 2, only the metadata record is created.
Actual file extraction is implemented in Phase 3.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project
    from app.db.models.source_chunk import SourceChunk
    from app.db.models.transformation_job import TransformationJob
    from app.db.models.canonical_content import CanonicalContent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    """
    A source document or text submitted by the user.

    Status lifecycle:
        uploaded → processing → ready → failed

    Relationships:
        project:            N-1 → Project
        source_chunks:      1-N → SourceChunk
        transformation_jobs: 1-N → TransformationJob
    """
    __tablename__ = "sources"

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
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="text",
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    storage_key: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="uploaded",
        index=True,
    )
    source_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="sources")
    source_chunks: Mapped[list["SourceChunk"]] = relationship(
        "SourceChunk",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    transformation_jobs: Mapped[list["TransformationJob"]] = relationship(
        "TransformationJob",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    canonical_content: Mapped["CanonicalContent | None"] = relationship(
        "CanonicalContent",
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Source id={self.id!s} type={self.source_type!r} status={self.status!r}>"
