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
from app.retrieval.service import RetrievalService


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


def make_project_with_chunks(db: Session, *, count: int = 3) -> tuple[Project, Source, list[SourceChunk]]:
    user = User(
        id=uuid.uuid4(),
        email="retrieval@example.test",
        name="Retrieval",
        role="operator",
    )
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Retrieval project")
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="txt",
        original_filename="retrieval.txt",
        mime_type="text/plain",
        file_size=128,
        language="en",
        status="ready",
        extracted_text="seed text",
    )
    db.add_all([user, project, source])
    db.flush()

    chunks = []
    for index in range(count):
        vector = [0.0] * 1536
        vector[0] = 1.0 - (index * 0.1)
        vector[1] = 0.1 + (index * 0.05)
        chunks.append(
            SourceChunk(
                id=uuid.uuid4(),
                source_id=source.id,
                chunk_index=index,
                content=f"chunk {index}",
                embedding=vector,
            )
        )
    db.add_all(chunks)
    db.commit()
    return project, source, chunks


def test_query_by_vector_returns_nearest_first(db):
    _, _, chunks = make_project_with_chunks(db)
    service = RetrievalService(embedding_service=EmbeddingService(provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536))

    results = service.query_by_vector(db, [1.0] + [0.0] * 1535, top_k=2)

    assert len(results) == 2
    assert results[0].chunk_index == 0
    assert results[1].chunk_index == 1
    assert results[0].distance >= 0.0
    assert results[0].content == "chunk 0"


def test_query_by_text_uses_embedding_service_and_returns_matches(db):
    _, _, _ = make_project_with_chunks(db)
    service = RetrievalService(embedding_service=EmbeddingService(provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536))

    results = service.query_by_text(db, "chunk 0", top_k=2)

    assert results
    assert results[0].content in {"chunk 0", "chunk 1", "chunk 2"}
    assert all(res.distance >= 0.0 for res in results)


def test_query_rejects_empty_text(db):
    service = RetrievalService()
    with pytest.raises(ValueError, match="empty"):
        service.query_by_text(db, "   ")


def test_query_rejects_invalid_dimension(db):
    service = RetrievalService()
    with pytest.raises(ValueError, match="dimensions"):
        service.query_by_vector(db, [1.0, 0.0], top_k=3)


def test_query_rejects_invalid_top_k(db):
    service = RetrievalService()
    with pytest.raises(ValueError, match="positive integer"):
        service.query_by_vector(db, [1.0] + [0.0] * 1535, top_k=0)


def test_query_excludes_null_embeddings(db):
    user = User(id=uuid.uuid4(), email="null@example.test", name="Null", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Null project")
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="txt",
        original_filename="null.txt",
        mime_type="text/plain",
        file_size=32,
        language="en",
        status="ready",
    )
    db.add_all([user, project, source])
    db.flush()
    chunk = SourceChunk(
        id=uuid.uuid4(),
        source_id=source.id,
        chunk_index=0,
        content="ignored",
        embedding=None,
    )
    db.add(chunk)
    db.commit()

    service = RetrievalService()
    results = service.query_by_vector(db, [1.0] + [0.0] * 1535, top_k=5)

    assert results == []


def test_query_does_not_mutate_db_state(db):
    _, source, chunks = make_project_with_chunks(db)
    before = [c.content for c in chunks]
    service = RetrievalService()

    results = service.query_by_vector(db, [1.0] + [0.0] * 1535, top_k=2)

    assert results
    assert [c.content for c in db.execute(select(SourceChunk).order_by(SourceChunk.chunk_index)).scalars().all()] == before
    assert db.get(Source, source.id).extracted_text == "seed text"


def test_query_returns_empty_when_no_matches(db):
    service = RetrievalService()
    results = service.query_by_vector(db, [1.0] + [0.0] * 1535, top_k=5)
    assert results == []
