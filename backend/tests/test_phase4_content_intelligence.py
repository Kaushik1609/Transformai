"""Phase 4 content intelligence tests."""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.content_intelligence.fake_provider import FakeContentAnalysisProvider
from app.content_intelligence.service import ContentIntelligenceService
from app.db.base import Base
from app.db.models.canonical_content import CanonicalContent
from app.db.models.content_analysis_trace import ContentAnalysisTrace
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.user import User


@pytest.fixture
def db():
    import app.db.models  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_source(db: Session) -> Source:
    user = User(id=uuid.uuid4(), email="phase4@example.test", name="Phase 4", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 4")
    source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", language="en", status="ready", extracted_text="A grounded source.")
    db.add_all([user, project, source])
    db.flush()
    db.add(SourceChunk(id=uuid.uuid4(), source_id=source.id, chunk_index=0, content="A grounded source."))
    db.commit()
    return source


def test_fake_provider_persists_grounded_canonical_content(db):
    source = make_source(db)
    result = ContentIntelligenceService(provider=FakeContentAnalysisProvider()).analyze_source(db, source.id)

    assert result.status == "completed"
    assert result.summary == "A grounded source."
    assert result.claims[0]["source_chunk_ids"]
    traces = db.execute(select(ContentAnalysisTrace)).scalars().all()
    assert traces and traces[0].source_id == source.id


def test_invalid_provider_output_is_rejected_without_source_mutation(db):
    source = make_source(db)
    original_text = source.extracted_text

    class InvalidProvider:
        def analyze(self, text, chunks):
            return {"summary": "unsupported", "claims": [{"text": "bad", "source_chunk_ids": [str(uuid.uuid4())]}]}

    with pytest.raises(ValueError, match="unknown source chunk"):
        ContentIntelligenceService(provider=InvalidProvider()).analyze_source(db, source.id)

    stored = db.get(Source, source.id)
    assert stored.extracted_text == original_text
    assert db.execute(select(CanonicalContent)).scalars().all()[0].status == "failed"


def test_missing_grounding_is_rejected(db):
    source = make_source(db)

    class UngroundedProvider:
        def analyze(self, text, chunks):
            return {"summary": "summary", "claims": [{"text": "claim", "source_chunk_ids": []}]}

    with pytest.raises(ValueError, match="at least 1"):
        ContentIntelligenceService(provider=UngroundedProvider()).analyze_source(db, source.id)
