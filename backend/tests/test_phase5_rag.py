"""Phase 5 RAG tests."""

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
from app.rag.service import RAGService
from app.retrieval.service import RetrievalService


@pytest.fixture
def db():
    import app.db.models  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_project_with_source_and_chunks(
    db: Session, *, count: int = 3, project_id: uuid.UUID | None = None
) -> tuple[Project, Source, list[SourceChunk]]:
    """Create a project with a source and embeddings."""
    user = User(id=uuid.uuid4(), email=f"rag-{uuid.uuid4()}@example.test", name="RAG", role="operator")
    if project_id is None:
        project_id = uuid.uuid4()
    project = Project(id=project_id, user_id=user.id, name="RAG project")
    source = Source(
        id=uuid.uuid4(),
        project_id=project_id,
        source_type="txt",
        original_filename="rag.txt",
        mime_type="text/plain",
        file_size=128,
        language="en",
        status="ready",
        extracted_text="rag context",
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
                content=f"chunk {index} content",
                embedding=vector,
            )
        )
    db.add_all(chunks)
    db.commit()
    return project, source, chunks


def test_retrieve_context_assembles_chunks_in_order(db):
    """Verify chunks are assembled in chunk_index order."""
    _, source, chunks = make_project_with_source_and_chunks(db, count=3)
    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "chunk 0", top_k=3)

    assert context.chunk_count == 3
    assert "chunk 0 content" in context.assembled_text
    assert "chunk 1 content" in context.assembled_text
    assert "chunk 2 content" in context.assembled_text


def test_retrieve_context_preserves_source_citations(db):
    """Ensure each citation includes full provenance."""
    project, source, chunks = make_project_with_source_and_chunks(db, count=2)
    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "chunk", top_k=2)

    assert len(context.citations) == 2
    citation_ids = {uuid.UUID(c.chunk_id) for c in context.citations}
    chunk_ids = {c.id for c in chunks}
    assert citation_ids == chunk_ids
    for citation in context.citations:
        assert citation.source_id == str(source.id)
        assert uuid.UUID(citation.chunk_id) in chunk_ids
        assert citation.chunk_index >= 0
        assert citation.evidence


def test_retrieve_context_respects_top_k(db):
    """Verify exactly top_k citations are returned."""
    _, _, _ = make_project_with_source_and_chunks(db, count=5)
    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "chunk", top_k=2)

    assert context.chunk_count == 2
    assert len(context.citations) == 2


def test_retrieve_context_respects_project_filter(db):
    """Verify retrieval restricts to project when specified."""
    project1_id = uuid.uuid4()
    project2_id = uuid.uuid4()
    _, _, chunks1 = make_project_with_source_and_chunks(db, count=2, project_id=project1_id)
    _, _, chunks2 = make_project_with_source_and_chunks(db, count=2, project_id=project2_id)

    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "chunk", top_k=5, project_id=project1_id)

    assert all(str(chunk.source.project_id) == str(project1_id) for chunk in chunks1)
    assert len(context.citations) <= 2


def test_retrieve_context_for_source_restricts_to_source(db):
    """Verify source_id parameter restricts retrieval."""
    project, source1, chunks1 = make_project_with_source_and_chunks(db, count=2)
    _, source2, chunks2 = make_project_with_source_and_chunks(db, count=2)

    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context_for_source(db, source1.id, "chunk", top_k=5)

    assert all(citation.source_id == str(source1.id) for citation in context.citations)
    assert not any(citation.source_id == str(source2.id) for citation in context.citations)


def test_retrieve_context_does_not_mutate_source_chunks(db):
    """Verify read-only retrieval."""
    _, source, chunks = make_project_with_source_and_chunks(db, count=2)
    before_content = [c.content for c in chunks]

    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "chunk", top_k=2)

    assert context.chunk_count == 2
    stored_chunks = db.execute(select(SourceChunk).order_by(SourceChunk.chunk_index)).scalars().all()
    assert [c.content for c in stored_chunks] == before_content


def test_retrieve_context_returns_empty_when_no_matches(db):
    """Verify empty result when query has no matches."""
    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    context = service.retrieve_context(db, "nonexistent query phrase")

    assert context.chunk_count == 0
    assert context.citations == []
    assert "no relevant context" in context.assembled_text


def test_retrieve_context_includes_task_context_metadata(db):
    """Verify task_context is preserved in RAGContext."""
    _, _, _ = make_project_with_source_and_chunks(db, count=1)
    service = RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )

    task_ctx = "Audience: executives; Tone: professional"
    context = service.retrieve_context(db, "chunk", top_k=1, task_context=task_ctx)

    assert context.task_context == task_ctx


def test_retrieve_context_rejects_invalid_query(db):
    """Verify empty query is rejected."""
    service = RAGService()

    with pytest.raises(ValueError, match="non-empty string"):
        service.retrieve_context(db, "   ")


def test_retrieve_context_rejects_invalid_top_k(db):
    """Verify invalid top_k is rejected."""
    service = RAGService()

    with pytest.raises(ValueError, match="positive integer"):
        service.retrieve_context(db, "valid query", top_k=0)
