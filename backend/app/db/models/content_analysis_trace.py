"""Relational provenance rows for canonical content items."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.canonical_content import CanonicalContent
    from app.db.models.source import Source
    from app.db.models.source_chunk import SourceChunk


class ContentAnalysisTrace(Base):
    __tablename__ = "content_analysis_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canonical_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    canonical_content: Mapped["CanonicalContent"] = relationship("CanonicalContent", back_populates="traces")
    source: Mapped["Source"] = relationship("Source")
    source_chunk: Mapped["SourceChunk"] = relationship("SourceChunk")
