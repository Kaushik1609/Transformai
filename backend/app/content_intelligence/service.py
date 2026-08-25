"""Application services for source-grounded content intelligence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.content_intelligence.provider import ContentAnalysisProvider
from app.content_intelligence.validator import validate_payload
from app.db.models.canonical_content import CanonicalContent
from app.db.models.content_analysis_trace import ContentAnalysisTrace
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _chunks_for_source(db: Session, source_id: uuid.UUID) -> tuple[Source, list[SourceChunk]]:
    source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source {source_id} was not found.")
    chunks = db.execute(
        select(SourceChunk).where(SourceChunk.source_id == source_id).order_by(SourceChunk.chunk_index)
    ).scalars().all()
    if not chunks:
        raise ValueError("Source has no chunks for content analysis.")
    return source, chunks


class ContentIntelligenceService:
    """Analyze a ready source and persist only validated provider output."""

    def __init__(self, provider: ContentAnalysisProvider):
        self.provider = provider

    def analyze_source(self, db: Session, source_id: uuid.UUID) -> CanonicalContent:
        source, chunks = _chunks_for_source(db, source_id)
        if source.status != "ready":
            raise ValueError("Only ready sources can be analyzed.")

        chunk_payload = [{"id": chunk.id, "chunk_index": chunk.chunk_index, "content": chunk.content} for chunk in chunks]
        try:
            payload = self.provider.analyze(source.extracted_text or "", chunk_payload)
            validated = validate_payload(payload, chunk_payload)
            now = _utcnow()
            canonical = db.execute(
                select(CanonicalContent).where(CanonicalContent.source_id == source.id)
            ).scalar_one_or_none()
            if canonical is None:
                canonical = CanonicalContent(id=uuid.uuid4(), source_id=source.id, project_id=source.project_id)
                db.add(canonical)
            canonical.status = "completed"
            canonical.title = validated.title
            canonical.summary = validated.summary
            canonical.content_metadata = validated.metadata
            for field in ("topics", "entities", "key_points", "claims", "statistics", "dates", "recommendations", "source_references"):
                setattr(canonical, field, [item.model_dump(mode="json") for item in getattr(validated, field)])
            canonical.error_message = None
            canonical.updated_at = now
            canonical.analyzed_at = now
            db.flush()

            db.query(ContentAnalysisTrace).filter(
                ContentAnalysisTrace.canonical_content_id == canonical.id
            ).delete(synchronize_session=False)
            chunk_by_id = {chunk.id: chunk for chunk in chunks}
            for item_type in ("topics", "entities", "key_points", "claims", "statistics", "dates", "recommendations", "source_references"):
                for item_index, item in enumerate(getattr(validated, item_type)):
                    for chunk_id in item.source_chunk_ids:
                        chunk = chunk_by_id[chunk_id]
                        db.add(ContentAnalysisTrace(
                            id=uuid.uuid4(), canonical_content_id=canonical.id, source_id=source.id,
                            source_chunk_id=chunk.id, item_type=item_type, item_index=item_index,
                            chunk_index=chunk.chunk_index, evidence=getattr(item, "evidence", None),
                        ))
            db.commit()
            db.refresh(canonical)
            return canonical
        except Exception as exc:
            db.rollback()
            _record_failure(db, source, str(exc))
            raise


def _record_failure(db: Session, source: Source, message: str) -> CanonicalContent:
    canonical = db.execute(select(CanonicalContent).where(CanonicalContent.source_id == source.id)).scalar_one_or_none()
    if canonical is None:
        canonical = CanonicalContent(id=uuid.uuid4(), source_id=source.id, project_id=source.project_id)
        db.add(canonical)
    canonical.status = "failed"
    canonical.error_message = message[:4000]
    canonical.updated_at = _utcnow()
    db.commit()
    db.refresh(canonical)
    return canonical


def create_pending_analysis(db: Session, source: Source) -> CanonicalContent:
    canonical = db.execute(select(CanonicalContent).where(CanonicalContent.source_id == source.id)).scalar_one_or_none()
    if canonical is None:
        canonical = CanonicalContent(id=uuid.uuid4(), source_id=source.id, project_id=source.project_id, status="pending")
        db.add(canonical)
    else:
        canonical.status = "pending"
        canonical.error_message = None
    db.commit()
    db.refresh(canonical)
    return canonical


async def get_analysis(db: AsyncSession, source_id: uuid.UUID) -> CanonicalContent | None:
    result = await db.execute(select(CanonicalContent).where(CanonicalContent.source_id == source_id))
    return result.scalar_one_or_none()


async def create_pending_analysis_async(db: AsyncSession, source: Source) -> CanonicalContent:
    """Create or reset the source's pending analysis record for an API request."""
    result = await db.execute(select(CanonicalContent).where(CanonicalContent.source_id == source.id))
    canonical = result.scalar_one_or_none()
    if canonical is None:
        canonical = CanonicalContent(
            id=uuid.uuid4(), source_id=source.id, project_id=source.project_id, status="pending"
        )
        db.add(canonical)
    else:
        canonical.status = "pending"
        canonical.error_message = None
    await db.flush()
    await db.refresh(canonical)
    return canonical
