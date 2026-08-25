"""
TransformIQ Backend — SourceChunk ORM Model

Used for RAG (Phase 5).

The embedding column is declared as a plain Text for Phase 2.
Phase 5 will replace this with a proper pgvector VECTOR column via migration.

Note: The pgvector extension must be enabled in PostgreSQL before the
vector column can be used. The initial migration enables the extension.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy import JSON as JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.source import Source


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceChunk(Base):
    """
    A chunk of a source document used for vector similarity search (RAG).

    The embedding column is structurally present but populated in Phase 5.

    Relationships:
        source: N-1 → Source
    """
    __tablename__ = "source_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536),
        nullable=True,
    )
    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    source: Mapped["Source"] = relationship(
        "Source",
        back_populates="source_chunks",
    )

    def __repr__(self) -> str:
        return f"<SourceChunk id={self.id!s} source_id={self.source_id!s} index={self.chunk_index}>"
