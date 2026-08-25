import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.user import User
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.ingestion.worker_processing import process_source_embeddings_with_session


class BadProvider:
    def embed_texts(self, texts):
        return [[0.1, 0.2] for _ in texts]


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


def make_source(db: Session, *, source_type="txt", content=b"phase 3e embedding") -> Source:
    project_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    source_id = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    user = User(
        id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        email="embed@example.test",
        name="Embed",
        role="operator",
    )
    project = Project(id=project_id, user_id=user.id, name="Embedding project")
    source = Source(
        id=source_id,
        project_id=project_id,
        source_type=source_type,
        original_filename=f"source.{source_type}",
        mime_type="text/plain",
        file_size=len(content),
        language="en",
        status="ready",
        extracted_text="phase 3e embedding",
    )
    db.add_all([user, project, source])
    db.flush()

    chunk = SourceChunk(
        id=uuid.uuid4(),
        source_id=source.id,
        chunk_index=0,
        content="phase 3e embedding",
        embedding=None,
    )
    db.add(chunk)
    db.commit()
    db.refresh(source)
    return source


def test_fake_provider_is_deterministic_and_dimensioned():
    provider = FakeEmbeddingProvider(dimensions=4)

    left = provider.embed_texts(["hello world"])
    right = provider.embed_texts(["hello world"])

    assert left == right
    assert len(left[0]) == 4
    assert all(isinstance(value, float) for value in left[0])


def test_embedding_service_validates_dimensions_and_batches():
    service = EmbeddingService(provider=FakeEmbeddingProvider(dimensions=4), dimensions=4)

    vectors = service.embed_texts(["apples", "bananas"])
    assert len(vectors) == 2
    assert all(len(vector) == 4 for vector in vectors)

    with pytest.raises(ValueError, match="dimensions"):
        EmbeddingService(provider=BadProvider(), dimensions=4).embed_texts(["bad"])

    with pytest.raises(ValueError, match="batch"):
        EmbeddingService(provider=FakeEmbeddingProvider(dimensions=4), dimensions=4).embed_texts([])


def test_process_source_embeddings_persists_vectors_without_deleting_source_data(db):
    source = make_source(db)

    result = process_source_embeddings_with_session(db, source.id)

    assert result.status == "ready"
    assert result.source_metadata["embedding_status"] == "completed"
    chunks = db.execute(
        select(SourceChunk).where(SourceChunk.source_id == source.id).order_by(SourceChunk.chunk_index)
    ).scalars().all()
    assert len(chunks) == 1
    assert len(chunks[0].embedding) == 1536
    assert source.extracted_text == "phase 3e embedding"


def test_process_source_embeddings_records_failure_without_destroying_data(db):
    source = make_source(db)
    chunk = db.execute(
        select(SourceChunk).where(SourceChunk.source_id == source.id)
    ).scalar_one()
    chunk.content = "still here"
    db.commit()

    class FailingProvider:
        def embed_texts(self, texts):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        process_source_embeddings_with_session(
            db,
            source.id,
            provider=FailingProvider(),
        )

    stored = db.get(Source, source.id)
    assert stored.status == "ready"
    assert stored.extracted_text == "phase 3e embedding"
    assert db.get(SourceChunk, chunk.id).content == "still here"
    assert "embedding_error" in (stored.source_metadata or {})
