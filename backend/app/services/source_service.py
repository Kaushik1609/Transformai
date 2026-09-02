"""
TransformIQ Backend — Source Service

Business logic for source metadata CRUD operations.
Actual document processing (extraction, chunking, embeddings) is Phase 3+.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.ingestion.documents import extract_docx, extract_pdf
from app.ingestion.queue import enqueue_source_ingestion
from app.ingestion.storage import LocalStorage
from app.ingestion.text import chunk_text, normalize_text
from app.ingestion.validation import validate_source

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_pending_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str,
    mime_type: str,
    language: str,
    metadata: dict[str, Any] | None = None,
) -> Source:
    """Validate and store an original, leaving extraction to the worker."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        source_metadata=metadata,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage = LocalStorage(settings.STORAGE_LOCAL_PATH)
    storage_key = storage.source_key(project_id, source.id, filename)
    storage.save(storage_key, content)
    source.storage_key = storage_key
    await db.flush()
    await db.refresh(source)
    return source


async def ingest_text_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str | None,
    mime_type: str,
    language: str,
    metadata: dict[str, Any] | None,
) -> Source:
    """Synchronously validate, store, normalize, and persist a text source."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    try:
        text = normalize_text(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Text source must be UTF-8 encoded.") from exc
    if not text:
        raise ValueError("Text source cannot be empty after normalization.")

    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        source_metadata=metadata,
        extracted_text=text,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage_filename = validated.filename or "original.txt"
    storage = LocalStorage(settings.STORAGE_LOCAL_PATH)
    storage_key = storage.source_key(project_id, source.id, storage_filename)
    storage.save(storage_key, content)
    source.storage_key = storage_key

    for chunk_index, chunk in enumerate(chunk_text(text)):
        db.add(
            SourceChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                chunk_index=chunk_index,
                content=chunk,
                embedding=None,
                created_at=_utcnow(),
            )
        )

    source.status = "ready"
    await db.flush()
    await db.refresh(source)
    logger.info(
        "Text source ingested",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=validated.source_type,
        chunk_count=len(source.source_chunks),
    )
    return source


async def ingest_document_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    content: bytes,
    source_type: str,
    filename: str | None,
    mime_type: str,
    language: str,
) -> Source:
    """Synchronously validate, extract, store, and persist a PDF or DOCX."""
    validated = validate_source(
        source_type=source_type,
        content=content,
        filename=filename,
        mime_type=mime_type,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    extracted_text = (
        extract_pdf(content)
        if validated.source_type == "pdf"
        else extract_docx(content)
    )
    text = normalize_text(extracted_text)
    if not text:
        raise ValueError("Document contains no usable text.")

    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=validated.source_type,
        original_filename=validated.filename,
        mime_type=validated.mime_type,
        file_size=validated.file_size,
        language=language,
        status="processing",
        extracted_text=text,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()

    storage = LocalStorage(settings.STORAGE_LOCAL_PATH)
    storage_key = storage.source_key(project_id, source.id, validated.filename or "original")
    storage.save(storage_key, content)
    source.storage_key = storage_key

    for chunk_index, chunk in enumerate(chunk_text(text)):
        db.add(
            SourceChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                chunk_index=chunk_index,
                content=chunk,
                embedding=None,
                created_at=_utcnow(),
            )
        )

    source.status = "ready"
    await db.flush()
    await db.refresh(source)
    logger.info(
        "Document source ingested",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=validated.source_type,
        chunk_count=len(source.source_chunks),
    )
    return source


async def create_source(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    original_filename: str | None,
    extracted_text: str | None,
    mime_type: str | None,
    language: str,
    metadata: dict[str, Any] | None,
) -> Source:
    """Create a new source metadata record."""
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type=source_type,
        original_filename=original_filename,
        extracted_text=extracted_text,
        mime_type=mime_type,
        language=language,
        status="uploaded",
        source_metadata=metadata,
        created_at=_utcnow(),
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    logger.info(
        "Source created",
        source_id=str(source.id),
        project_id=str(project_id),
        source_type=source_type,
    )
    return source


async def list_sources(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
) -> list[Source]:
    """Return all sources for a project."""
    result = await db.execute(
        select(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.created_at.desc())
    )
    return list(result.scalars().all())


async def get_source(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
) -> Source | None:
    """Return a single source by ID (no user scope — caller must verify project ownership)."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    return result.scalar_one_or_none()


async def get_source_owned(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Source | None:
    """
    Return a single source by ID, scoped to an owning user.

    Enforces authorization at the database level by joining through the
    parent project to its owner. A source that exists but belongs to another
    user is indistinguishable from a nonexistent source (returns ``None``).

    Phase 9A — SQL-level ownership scoping to prevent IDOR / BOLA.
    """
    result = await db.execute(
        select(Source)
        .join(Project, Source.project_id == Project.id)
        .where(
            Source.id == source_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_source(
    db: AsyncSession,
    *,
    source: Source,
) -> None:
    """Delete a source and all its cascaded children."""
    await db.delete(source)
    await db.flush()
    logger.info("Source deleted", source_id=str(source.id))
