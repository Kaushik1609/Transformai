"""Phase 3D tests for shared worker source processing."""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.user import User
from app.ingestion.storage import LocalStorage
from app.ingestion.worker_processing import process_source_with_session


@pytest.fixture
def db():
    import app.db.models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_source(db: Session, tmp_path, *, source_type="txt", content=b"worker text") -> Source:
    project_id = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    source_id = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    user = User(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        email="worker@example.test",
        name="Worker",
        role="operator",
    )
    project = Project(id=project_id, user_id=user.id, name="Worker project")
    source = Source(
        id=source_id,
        project_id=project_id,
        source_type=source_type,
        original_filename=f"source.{source_type}",
        mime_type="text/plain" if source_type == "txt" else "application/pdf",
        file_size=len(content),
        language="en",
        status="processing",
    )
    db.add_all([user, project, source])
    db.flush()
    key = LocalStorage.source_key(project_id, source_id, source.original_filename)
    LocalStorage(tmp_path).save(key, content)
    source.storage_key = key
    db.commit()
    db.refresh(source)
    return source


def test_worker_marks_source_ready_and_creates_chunks(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    source = make_source(db, tmp_path, content=b"first line\r\n\r\nsecond line")

    result = process_source_with_session(db, source.id)

    assert result.status == "ready"
    assert result.extracted_text == "first line\n\nsecond line"
    chunks = db.execute(
        select(SourceChunk)
        .where(SourceChunk.source_id == source.id)
        .order_by(SourceChunk.chunk_index)
    ).scalars().all()
    assert [chunk.chunk_index for chunk in chunks] == [0]
    assert all(chunk.embedding is None for chunk in chunks)


def test_worker_marks_corrupt_pdf_failed(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    source = make_source(db, tmp_path, source_type="pdf", content=b"corrupt")

    with pytest.raises(ValueError, match="read the PDF"):
        process_source_with_session(db, source.id)

    failed = db.get(Source, source.id)
    assert failed.status == "failed"
    assert "ingestion_error" in failed.source_metadata


def test_worker_requires_authoritative_existing_source(db):
    with pytest.raises(ValueError, match="was not found"):
        process_source_with_session(db, uuid.UUID("22222222-2222-4222-8222-222222222222"))
