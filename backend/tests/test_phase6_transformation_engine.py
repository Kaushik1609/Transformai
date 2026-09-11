"""Phase 6 — Transformation Engine tests.

Covers the LangGraph transformation workflow, multi-output support, lifecycle
status transitions, partial success, RAG context integration, the verification
hook, queue enqueueing, and cancellation.  Uses deterministic fake/stub
generators and providers — no external LLM API access is required.
"""

import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
import app.db.models  # noqa: F401
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.rag.service import RAGService
from app.retrieval.service import RetrievalService
import app.transformation.queue  # noqa: F401
import app.transformation.service  # noqa: F401
import app.transformation.generators  # noqa: F401
from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.db.models.verification_result import VerificationResult
from app.transformation.generators import get_generator as registry_get_generator
from app.transformation.queue import (
    cancel_transformation_job,
    enqueue_transformation_job,
    get_transformation_queue,
)
from app.transformation.service import run_transformation_job
from app.main import app as fastapi_app


TEST_USER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TEST_USER = CurrentUser(TEST_USER_ID, "phase6@example.test", "Phase 6", "operator")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_database(with_canonical: bool = True, n_chunks: int = 2):
    """Create an in-memory sqlite DB seeded with a ready project/source/canonical."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"phase6-{uuid.uuid4().hex}@example.test", name="P6", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 6")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line one.\nSource line two.",
        )
        db.add_all([user, project, source])
        db.flush()
        for i in range(n_chunks):
            vector = [0.0] * 1536
            vector[0] = 1.0 - (i * 0.1)
            db.add(SourceChunk(id=uuid.uuid4(), source_id=source.id, chunk_index=i,
                               content=f"chunk {i} source content", embedding=vector))
        if with_canonical:
            db.add(CanonicalContent(
                id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
                title="Test Source", summary="A test source summary.",
                key_points=[{"text": "First key point", "source_chunk_ids": []}],
                recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            ))
        db.commit()
    return engine, project.id, source.id


def make_job(engine, project_id: uuid.UUID, source_id: uuid.UUID, output_types: list[str],
             config: dict[str, Any] | None = None, status: str = "queued") -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as db:
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        if config:
            for k, v in config.items():
                setattr(cfg, k, v)
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=cfg.id, requested_outputs={"output_types": output_types}, status=status,
        )
        db.add(job)
        db.commit()
        return job.id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(scope="function")
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture(scope="function")
def client(async_db_session) -> Generator[TestClient, None, None]:
    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return TEST_USER

    app = fastapi_app
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _rag_service():
    return RAGService(
        retrieval_service=RetrievalService(
            embedding_service=EmbeddingService(
                provider=FakeEmbeddingProvider(dimensions=1536), dimensions=1536
            )
        )
    )


class CannedRAGService:
    """Stub RAG service returning fixed context so tests are deterministic."""

    def __init__(self):
        self.calls = []

    def retrieve_context_for_source(self, db, source_id, query, *, project_id=None, top_k=5, task_context=None):
        self.calls.append(
            {"source_id": str(source_id), "query": query, "project_id": str(project_id) if project_id else None}
        )
        from datetime import datetime
        from app.rag.schemas import RAGCitation, RAGContext

        return RAGContext(
            query=query,
            assembled_text="[Chunk 0]\nchunk 0 source content\n\n[Chunk 1]\nchunk 1 source content",
            citations=[
                RAGCitation(source_id=str(source_id), chunk_id=str(uuid.uuid4()), chunk_index=0,
                            evidence="chunk 0 source content", relevance_score=0.9)
            ],
            chunk_count=1,
            task_context=task_context,
            metadata={},
            retrieved_at=datetime.now(),
        )

    def retrieve_context(self, *args, **kwargs):
        raise AssertionError("generic retrieve_context should not be used by the workflow")


class FailingGenerator:
    """A stub generator that always raises, used to prove independent failure."""

    output_type = "linkedin"

    def generate(self, **kwargs):
        raise RuntimeError("deterministic generator failure")


def _partial_get_generator(output_type: str) -> Any:
    if output_type == "linkedin":
        return FailingGenerator()
    return registry_get_generator(output_type)


# ---------------------------------------------------------------------------
# 1. Transformation job creation + persistence
# ---------------------------------------------------------------------------

def test_transformation_job_creation_queued(db):
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        assert job is not None
        assert job.status == "queued"
        assert job.requested_outputs["output_types"] == ["summary"]
    engine.dispose()


# ---------------------------------------------------------------------------
# 2. Successful enqueue (queue helper payload is only the job ID)
# ---------------------------------------------------------------------------

class FakeRQJob:
    id = "rq-trans-123"


class FakeQueue:
    """Minimal stand-in for ``rq.Queue`` that models RQ 2.0 arg handling.

    RQ 2.0 reserves parameters such as ``job_id`` and ``job_timeout`` and pops
    them before invoking the callable, so an enqueued ``job`` exposes ``args``
    = the callable's positional arguments (the function reference is *not*
    included) and ``kwargs`` = the callable's keyword arguments.
    """

    def __init__(self):
        self.calls = []
        self.job_ids = []
        self._jobs = {}

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        job = FakeRQJob()
        # Real RQ stores only the callable's args — the function reference is
        # used for import resolution and is not part of `job.args`.
        self._jobs[job.id] = {
            "args": args[1:],
            "kwargs": dict(kwargs),
            "cancelled": False,
        }
        self.job_ids.append(job.id)
        return job

    def fetch_job(self, rq_job_id):
        return FakeFetchableJob(self._jobs.get(rq_job_id))


class FakeFetchableJob:
    def __init__(self, meta):
        self.meta = meta

    @property
    def args(self):
        return self.meta.get("args", ())

    @property
    def kwargs(self):
        return self.meta.get("kwargs", {})

    def cancel(self):
        self.meta["cancelled"] = True


def test_enqueue_payload_contains_only_job_id():
    queue = FakeQueue()
    job_id = uuid.uuid4()
    rq_id = enqueue_transformation_job(job_id, queue=queue)
    assert rq_id == "rq-trans-123"
    args, kwargs = queue.calls[0]
    # The DB job ID must be passed positionally (RQ 2.0 reserves the `job_id`
    # keyword for the RQ job's own ID and strips it before invoking the callable).
    assert args == ("worker.process_transformation", str(job_id))
    assert "job_id" not in kwargs
    assert set(kwargs) >= {"job_timeout", "result_ttl", "on_failure"}


def test_transformation_failure_handler_recovers_job_id_from_args():
    # The failure handler extracts the DB job ID from job.args[0] (real RQ
    # exposes only the callable's positional args). Verify recovery works for
    # the payload enqueued by enqueue_transformation_job.
    queue = FakeQueue()
    job_id = uuid.uuid4()
    enqueue_transformation_job(job_id, queue=queue)
    rq_job = queue.fetch_job(queue.job_ids[0])
    assert rq_job.args[0] == str(job_id)


def test_enqueue_uses_dedicated_transformation_queue():
    assert get_transformation_queue().name == "transformation"


# ---------------------------------------------------------------------------
# 3. Canonical-content requirement
# ---------------------------------------------------------------------------

def test_canonical_content_missing_fails_gracefully():
    engine, project_id, source_id = make_database(with_canonical=False)
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id)
    assert result["outputs_completed"] == 0
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        assert job.status == "failed"
        assert "Canonical content" in job.error_message
        assert s.execute(select(Output)).scalars().all() == []
        # source is not corrupted
        assert s.get(Source, source_id).extracted_text == "Source line one.\nSource line two."
    engine.dispose()


def test_canonical_content_not_completed_fails_gracefully():
    engine, project_id, source_id = make_database(with_canonical=True)
    with Session(engine) as s:
        canonical = s.execute(select(CanonicalContent).where(CanonicalContent.source_id == source_id)).scalar_one()
        canonical.status = "pending"
        s.commit()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id)
    assert result["outputs_completed"] == 0
    with Session(engine) as s:
        assert s.get(TransformationJob, job_id).status == "failed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 4. Single output generation
# ---------------------------------------------------------------------------

def test_single_output_generation():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id)
    assert result["outputs_completed"] == 1
    assert result["outputs_failed"] == 0
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        assert job.status == "completed"
        outputs = s.execute(select(Output)).scalars().all()
        assert len(outputs) == 1
        out = outputs[0]
        assert out.output_type == "summary"
        assert out.status == "completed"
        assert "Test Source" in out.text_content
        assert out.error_message is None
    engine.dispose()


# ---------------------------------------------------------------------------
# 5. Multiple output generation (one source -> many outputs)
# ---------------------------------------------------------------------------

def test_multiple_output_generation():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary", "linkedin", "advisory"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id)
    assert result["outputs_completed"] == 3
    assert result["outputs_failed"] == 0
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        assert job.status == "completed"
        outputs = {o.output_type: o for o in s.execute(select(Output)).scalars().all()}
        assert set(outputs) == {"summary", "linkedin", "advisory"}
        assert all(o.status == "completed" for o in outputs.values())
        # each output independently rendered from the same canonical content
        assert "Test Source" in outputs["summary"].text_content
        assert "Just published" in outputs["linkedin"].text_content
        assert "Advisory" in outputs["advisory"].text_content
    engine.dispose()


# ---------------------------------------------------------------------------
# 6. Independent output failure / partial success
# ---------------------------------------------------------------------------

def test_independent_output_failure_partial_success():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary", "linkedin", "advisory"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id, get_generator=_partial_get_generator)
    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 1
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        # partial success keeps the job completed and preserves successful outputs
        assert job.status == "completed"
        outputs = {o.output_type: o for o in s.execute(select(Output)).scalars().all()}
        assert outputs["summary"].status == "completed"
        assert outputs["advisory"].status == "completed"
        assert outputs["linkedin"].status == "failed"
        assert "deterministic generator failure" in outputs["linkedin"].error_message
    engine.dispose()


def test_all_outputs_failed_marks_job_failed():
    engine, project_id, source_id = make_database()

    class AlwaysFail:
        output_type = "summary"

        def generate(self, **kw):
            raise RuntimeError("fail")

    def getgen(output_type):
        return AlwaysFail()

    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        result = run_transformation_job(s, job_id, get_generator=getgen)
    assert result["outputs_completed"] == 0
    assert result["outputs_failed"] == 1
    with Session(engine) as s:
        assert s.get(TransformationJob, job_id).status == "failed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 7. Job status transitions
# ---------------------------------------------------------------------------

def test_job_status_transitions_queued_to_completed():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        assert s.get(TransformationJob, job_id).status == "queued"
        run_transformation_job(s, job_id)
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        assert job.status == "completed"
        assert job.completed_at is not None
    engine.dispose()


def test_cancelled_job_is_skipped():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"], status="cancelled")
    with Session(engine) as s:
        result = run_transformation_job(s, job_id)
    assert result.get("skipped") is True
    with Session(engine) as s:
        assert s.get(TransformationJob, job_id).status == "cancelled"
    engine.dispose()


# ---------------------------------------------------------------------------
# 8. Output status transitions
# ---------------------------------------------------------------------------

def test_output_status_transitions_completed():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        job = s.get(TransformationJob, job_id)
        from app.db.models.output import Output as OModel

        out = OModel(id=uuid.uuid4(), job_id=job.id, output_type="summary", status="generating")
        s.add(out)
        s.commit()
        # Phase 11E idempotency: a pre-existing output row for this job/output_type
        # is reused (not duplicated) and driven to completed by the run, so exactly
        # one output row remains.
        run_transformation_job(s, job_id)
    with Session(engine) as s:
        outputs = s.execute(select(Output)).scalars().all()
        assert len(outputs) == 1  # pre-seeded row reused -> no duplicate
        assert outputs[0].status == "completed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 9. Cancellation behavior
# ---------------------------------------------------------------------------

def test_cancel_revokes_queued_job():
    queue = FakeQueue()
    job_id = uuid.uuid4()
    enqueue_transformation_job(job_id, queue=queue)
    cancelled = cancel_transformation_job(job_id, queue=queue)
    assert cancelled is True


def test_cancel_returns_false_when_none_queued():
    queue = FakeQueue()
    cancelled = cancel_transformation_job(uuid.uuid4(), queue=queue)
    assert cancelled is False


# ---------------------------------------------------------------------------
# 10. RAG context integration
# ---------------------------------------------------------------------------

def test_rag_context_retrieved_when_required():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"],
                      config={"communication_objective": "decision support"})
    rag = CannedRAGService()
    with Session(engine) as s:
        result = run_transformation_job(s, job_id, rag_service=rag)
    assert result["outputs_completed"] == 1
    # RAG was invoked and fed into the generator
    assert len(rag.calls) == 1
    assert rag.calls[0]["source_id"] == str(source_id)
    with Session(engine) as s:
        out = s.execute(select(Output)).scalars().one()
        assert "source context" in out.structured_content["text"].lower()
        assert "chunk 0 source content" in out.structured_content["text"]
    engine.dispose()


def test_no_rag_when_not_required():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    rag = CannedRAGService()
    with Session(engine) as s:
        result = run_transformation_job(s, job_id, rag_service=rag)
    assert result["outputs_completed"] == 1
    # RAG must not be invoked when the transformation does not require it
    assert rag.calls == []
    with Session(engine) as s:
        out = s.execute(select(Output)).scalars().one()
        assert "source context" not in out.structured_content["text"].lower()
    engine.dispose()


# ---------------------------------------------------------------------------
# 11. LangGraph workflow execution
# ---------------------------------------------------------------------------

def test_langgraph_workflow_executes_all_stages():
    from app.transformation.graph import TransformationDependencies, build_transformation_graph

    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary", "linkedin"])
    with Session(engine) as s:
        deps = TransformationDependencies(session=s)
        graph = build_transformation_graph(deps)
        # compiled LangGraph the workflow can invoke
        result = graph.invoke({"job_id": str(job_id)})
        assert len(result["outputs"]) == 2
        assert all(o["status"] == "completed" for o in result["outputs"])
        assert len(result["verification_hooks"]) == 2
        s.commit()
    engine.dispose()


# ---------------------------------------------------------------------------
# 12. Verification hook invocation
# ---------------------------------------------------------------------------

def test_verification_hook_invoked_and_persisted():
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as s:
        run_transformation_job(s, job_id)
    with Session(engine) as s:
        results = s.execute(select(VerificationResult)).scalars().all()
        assert len(results) == 1
        # Phase 8 replaces the old pending_phase8 marker with a real result.
        assert results[0].details["status"] == "completed"
        assert results[0].overall_status == "passed"
        assert results[0].claims_checked == 0
        assert results[0].grounding_score is None
    engine.dispose()


# ---------------------------------------------------------------------------
# 13. Worker loads job by ID
# ---------------------------------------------------------------------------

def test_worker_loads_job_by_id(monkeypatch):
    """Simulate the RQ handler entry point receiving only the job ID."""
    engine, project_id, source_id = make_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])

    captured = {}

    def fake_handler(session, jid, **kwargs):
        captured["job_id"] = jid
        record = session.get(TransformationJob, jid)
        captured["loaded_from_db"] = record is not None
        return run_transformation_job(session, jid, **kwargs)

    monkeypatch.setattr("app.transformation.service.run_transformation_job", fake_handler)

    # Mirror worker.process_transformation: engine + select by the string job id.
    from sqlalchemy.orm import Session as ORMSession

    with Session(engine) as s:
        result = fake_handler(s, job_id)
    assert captured["loaded_from_db"] is True
    assert captured["job_id"] == job_id
    assert result["outputs_completed"] == 1
    engine.dispose()


# ---------------------------------------------------------------------------
# API: POST enqueues, cancel revokes (Phase 2 contract preserved)
# ---------------------------------------------------------------------------

def _seed_project_sources_configuration(client: TestClient) -> tuple[str, str, str]:
    pid = client.post("/api/v1/projects", json={"name": "Phase 6 API"}).json()["data"]["id"]
    sid = client.post(
        f"/api/v1/projects/{pid}/sources/async", json={"text": "api source text", "language": "en"}
    ).json()["data"]["id"]
    cid = client.post(
        f"/api/v1/projects/{pid}/configurations",
        json={"language": "English", "detail_level": "standard"},
    ).json()["data"]["id"]
    return pid, sid, cid


def test_api_create_transformation_enqueues(client, monkeypatch):
    queued = []
    fake_queue = FakeQueue()
    monkeypatch.setattr("app.api.v1.transformations.get_transformation_queue", lambda: fake_queue)
    pid, sid, cid = _seed_project_sources_configuration(client)
    resp = client.post(
        "/api/v1/transformations",
        json={"project_id": pid, "source_id": sid, "configuration_id": cid, "output_types": ["summary"]},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "queued"
    args, kwargs = fake_queue.calls[0]
    # The DB job ID is passed positionally; RQ 2.0 consumes reserved kwargs
    # like `job_id` (so it must not be forwarded as a callable kwarg).
    assert args == ("worker.process_transformation", resp.json()["data"]["id"])
    assert "job_id" not in kwargs
    assert set(kwargs) >= {"job_timeout", "result_ttl", "on_failure"}


def test_api_cancel_transformation_revokes_queued_job(client, monkeypatch):
    fake_queue = FakeQueue()
    monkeypatch.setattr("app.api.v1.transformations.get_transformation_queue", lambda: fake_queue)
    pid, sid, cid = _seed_project_sources_configuration(client)
    job_id = client.post(
        "/api/v1/transformations",
        json={"project_id": pid, "source_id": sid, "configuration_id": cid, "output_types": ["summary"]},
    ).json()["data"]["id"]
    resp = client.post(f"/api/v1/transformations/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


def test_api_cancel_completed_job_conflict(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.transformations.get_transformation_queue", lambda: FakeQueue())
    pid, sid, cid = _seed_project_sources_configuration(client)
    job_id = client.post(
        "/api/v1/transformations",
        json={"project_id": pid, "source_id": sid, "configuration_id": cid, "output_types": ["summary"]},
    ).json()["data"]["id"]
    # force the job into a non-cancellable state
    resp = client.post(f"/api/v1/transformations/{job_id}/cancel")
    assert resp.status_code == 200
    second = client.post(f"/api/v1/transformations/{job_id}/cancel")
    assert second.status_code == 409


def test_api_create_transformation_with_fake_llm_provider(client, monkeypatch):
    monkeypatch.setattr(settings, "MALWARE_SCAN_ENABLED", False)
    fake_queue = FakeQueue()
    monkeypatch.setattr("app.api.v1.transformations.get_transformation_queue", lambda: fake_queue)
    pid, sid, cid = _seed_project_sources_configuration(client)
    resp = client.post(
        "/api/v1/transformations",
        json={
            "project_id": pid,
            "source_id": sid,
            "configuration_id": cid,
            "output_types": ["summary"],
            "llm_provider": "fake",
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "queued"
    assert data["requested_outputs"]["llm_provider"] == "fake"

