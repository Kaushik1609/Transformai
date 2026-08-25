"""Shared synchronous source processing used by the RQ worker."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.embeddings.service import EmbeddingService
from app.ingestion.documents import DocumentExtractionError, extract_docx, extract_pdf
from app.ingestion.queue import enqueue_source_embedding, get_embedding_queue
from app.ingestion.storage import LocalStorage
from app.ingestion.text import chunk_text, normalize_text


def process_source_with_session(db: Session, source_id: uuid.UUID) -> Source:
    """Process one stored source and transition it to ready or failed."""
    source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source {source_id} was not found.")

    try:
        if not source.storage_key:
            raise ValueError("Source has no stored original file.")
        content = LocalStorage(settings.STORAGE_LOCAL_PATH).read(source.storage_key)
        if source.source_type in {"text", "txt"}:
            extracted = content.decode("utf-8")
        elif source.source_type == "pdf":
            extracted = extract_pdf(content)
        elif source.source_type == "docx":
            extracted = extract_docx(content)
        else:
            raise ValueError(f"Unsupported source type: {source.source_type!r}.")

        normalized = normalize_text(extracted)
        if not normalized:
            raise ValueError("Source contains no usable text.")

        db.execute(delete(SourceChunk).where(SourceChunk.source_id == source.id))
        chunks = list(chunk_text(normalized))
        for chunk_index, content_chunk in enumerate(chunks):
            db.add(
                SourceChunk(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    chunk_index=chunk_index,
                    content=content_chunk,
                    embedding=None,
                    created_at=datetime.now(timezone.utc),
                )
            )
        source.extracted_text = normalized
        source.status = "ready"
        source_metadata = dict(source.source_metadata or {})
        source_metadata["chunk_count"] = len(chunks)
        source_metadata["embedding_status"] = "queued"
        source.source_metadata = source_metadata
        db.commit()
        db.refresh(source)

        try:
            enqueue_source_embedding(source.id, queue=get_embedding_queue())
        except Exception as exc:  # pragma: no cover - defensive best effort
            source_metadata = dict(source.source_metadata or {})
            source_metadata["embedding_status"] = "failed"
            source_metadata["embedding_queue_error"] = str(exc)
            source.source_metadata = source_metadata
            db.commit()
        return source
    except (DocumentExtractionError, UnicodeDecodeError, OSError, ValueError) as exc:
        db.rollback()
        failed_source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if failed_source is not None:
            failed_source.status = "failed"
            failed_source.source_metadata = {
                **(failed_source.source_metadata or {}),
                "ingestion_error": str(exc),
            }
            db.commit()
        raise


def process_source_embeddings_with_session(
    db: Session,
    source_id: uuid.UUID,
    *,
    provider=None,
) -> Source:
    """Generate deterministic embeddings for a ready source and persist them without deleting source data."""
    source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source {source_id} was not found.")

    try:
        chunks = db.execute(
            select(SourceChunk)
            .where(SourceChunk.source_id == source.id)
            .order_by(SourceChunk.chunk_index)
        ).scalars().all()
        if not chunks:
            raise ValueError("Source has no chunks to embed.")

        texts = [chunk.content for chunk in chunks]
        service = EmbeddingService(provider=provider, dimensions=settings.EMBEDDING_DIMENSIONS)
        vectors = service.embed_texts(texts)
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector

        source_metadata = dict(source.source_metadata or {})
        source_metadata["embedding_status"] = "completed"
        source_metadata["embedding_dimensions"] = settings.EMBEDDING_DIMENSIONS
        source_metadata["embedding_count"] = len(chunks)
        source.source_metadata = source_metadata
        db.commit()
        db.refresh(source)
        return source
    except Exception as exc:
        db.rollback()
        failed_source = db.execute(select(Source).where(Source.id == source_id)).scalar_one_or_none()
        if failed_source is not None:
            metadata = dict(failed_source.source_metadata or {})
            metadata["embedding_status"] = "failed"
            metadata["embedding_error"] = str(exc)
            failed_source.source_metadata = metadata
            db.commit()
        raise
