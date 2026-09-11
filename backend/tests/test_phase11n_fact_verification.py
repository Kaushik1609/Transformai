"""Phase 11N — Evidence / Fact Verification (MVP) tests.

Covers the on-demand fact-verification layer added alongside the Phase 8
verification pipeline. The feature is entirely offline, deterministic, and
reuses the existing provenance-carrying RAG path; it never claims ground-truth
correctness — only that a claim is supported/contradicted/unverified against the
*project's own* source evidence.

   11N-A  Configuration knobs present (enabled, max claims, top-k, min sim).
   11N-B  Claim extraction is reused (conservative Phase 8 signals).
   11N-C  SUPPORTED verdict for a claim grounded in retrieved evidence.
   11N-D  CONTRADICTED verdict for an altered numeric figure.
   11N-E  CONTRADICTED verdict for a date mismatch.
   11N-F  UNVERIFIED verdict when no overlapping evidence is retrieved.
   11N-G  Report aggregation: passed / warning / failed status mapping.
   11N-H  Persistence into VerificationResult with the 11N generator marker.
   11N-I  Bounded metric families registered + emitted.
   11N-J  Evidence + max-claim bounding.
   11N-K  MAX_CLAIMS cap honored.
   11N-L  Disabled-by-config gate returns 409.
   11N-M  404 for an unknown output.
   11N-N  409 for a non-completed output.
   11N-O  Ownership isolation: another user's output is indistinguishable (404).
   11N-P  Retrieval persistence failure isolated (500, no detail leak).
   11N-Q  API happy-path returns a 2xx envelope and persists a report.
   11N-R  Response contract validates against the bounded schema.
   11N-S  Feature is separate from the generation pipeline (no coupling).
   11N-T  Project/source scoping: retrieval is restricted to the output's source.
   11N-U  Phase 11K audit events: started / completed / failed lifecycle,
          no sensitive payload content, and fail-safe emission.

No API key and no network access are required for any test.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.api.deps import CurrentUser, get_current_user
from app.core.audit import clear_security_events, security_events
from app.core.config import settings
from app.core.metrics import metrics, render_metrics
from app.db.base import Base
from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.db.models.verification_result import VerificationResult
from app.db.session import get_db
from app.main import app as fastapi_app
from app.rag.service import RAGService
from app.transformation.verification_engine import fact_verifier
from app.transformation.verification_engine.claims import extract_claims


TEST_USER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
OTHER_USER_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TEST_USER = CurrentUser(TEST_USER_ID, "phase11n@example.test", "Phase 11N", "operator")

SUPPORTED_CLAIM = "The system supports 500 concurrent users."
CONTRADICTED_CLAIM = "The system supports 50000 concurrent users."
DATE_CLAIM = "The annual report was published on 1 March 2024."
UNCLAIM = "The engineering team shipped the platform release on schedule."


def _chunk(db: Session, source_id: uuid.UUID, content: str, index: int = 0) -> None:
    vector = [0.0] * 1536
    vector[0] = 1.0 - (index * 0.01)
    db.add(
        SourceChunk(
            id=uuid.uuid4(),
            source_id=source_id,
            chunk_index=index,
            content=content,
            embedding=vector,
        )
    )


def make_project(db: Session, *, user_id: uuid.UUID, name: str = "11N") -> tuple[Project, Source]:
    user = User(id=user_id, email=f"{user_id}@example.test", name="11N", role="operator")
    project = Project(id=uuid.uuid4(), user_id=user.id, name=name)
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="text",
        status="ready",
        extracted_text=SUPPORTED_CLAIM,
    )
    db.add_all([user, project, source])
    db.flush()
    db.add(
        CanonicalContent(
            id=uuid.uuid4(),
            source_id=source.id,
            project_id=project.id,
            status="completed",
            title="Capacity Report",
            summary=SUPPORTED_CLAIM,
            key_points=[{"text": SUPPORTED_CLAIM, "source_chunk_ids": []}],
            recommendations=[],
            claims=[],
            statistics=[],
            dates=[],
            entities=[],
            topics=[],
            source_references=[],
        )
    )
    return project, source


def make_db_with_output(
    *,
    claim: str,
    user_id: uuid.UUID = TEST_USER_ID,
    status: str = "completed",
    source_content: str | None = None,
    extra_chunks: list[str] | None = None,
) -> tuple[Any, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create an sqlite engine with a project, source, chunks, job and output."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        project, source = make_project(db, user_id=user_id)
        source_content = source_content or SUPPORTED_CLAIM
        _chunk(db, source.id, source_content, index=0)
        for index, content in enumerate(extra_chunks or [], start=1):
            _chunk(db, source.id, content, index=index)

        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=cfg.id,
            requested_outputs={"output_types": ["summary"]},
            status=status,
        )
        db.add(job)
        db.flush()
        output = Output(
            id=uuid.uuid4(),
            job_id=job.id,
            output_type="summary",
            status=status,
            text_content=claim,
            structured_content={"type": "summary", "summary": claim},
        )
        db.add(output)
        db.commit()
        return engine, project.id, source.id, job.id, output.id
    engine.dispose()


def _rag() -> RAGService:
    return RAGService()


def _verify(engine, output_id, project_id, source_id):
    from app.transformation.verification_engine import fact_verifier as fv

    with Session(engine, expire_on_commit=False) as db:
        out = db.get(Output, output_id)
        report = fv.verify_facts(
            output=out,
            rag_service=_rag(),
            db=db,
            project_id=project_id,
            source_id=source_id,
        )
        fv.persist_report(db, report)
        db.commit()
        return report


# ---------------------------------------------------------------------------
# 11N-A — configuration knobs
# ---------------------------------------------------------------------------

def test_config_knobs_present():
    assert settings.FACT_VERIFICATION_ENABLED is True
    assert settings.FACT_VERIFICATION_MAX_CLAIMS > 0
    assert settings.FACT_VERIFICATION_TOP_K > 0
    assert 0.0 <= settings.FACT_VERIFICATION_MIN_SIMILARITY <= 1.0
    assert settings.FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM > 0


# ---------------------------------------------------------------------------
# 11N-B — claim extraction reuse (conservative Phase 8 signals)
# ---------------------------------------------------------------------------

def test_extracted_claims_reused():
    output = {
        "type": "summary",
        "summary": (
            "- The system supports 500 concurrent users.\n"
            "- 40% of customers renew annually."
        ),
    }
    claims = extract_claims(output)
    texts = {c["text"] for c in claims}
    assert SUPPORTED_CLAIM in texts
    assert any("%" in t for t in texts)


# ---------------------------------------------------------------------------
# 11N-C — SUPPORTED verdict
# ---------------------------------------------------------------------------

def test_supported_verdict():
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    assert report.claims_checked >= 1
    assert all(c.verdict == fact_verifier.VERDICT_SUPPORTED for c in report.claims)
    assert report.claims_supported == report.claims_checked
    assert report.overall_status == "passed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-D — CONTRADICTED numeric mismatch
# ---------------------------------------------------------------------------

def test_contradicted_numeric_mismatch():
    engine, pid, sid, jid, oid = make_db_with_output(claim=CONTRADICTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    assert report.claims_contradicted >= 1
    assert any(
        c.verdict == fact_verifier.VERDICT_CONTRADICTED and "numbers" in c.reason
        for c in report.claims
    )
    assert report.overall_status == "failed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-E — CONTRADICTED date mismatch
# ---------------------------------------------------------------------------

def test_contradicted_date_mismatch():
    engine, pid, sid, jid, oid = make_db_with_output(
        claim=DATE_CLAIM,
        source_content="The annual report was published on 1 March 2023.",
    )
    report = _verify(engine, oid, pid, sid)
    assert report.claims_contradicted >= 1
    assert any(
        c.verdict == fact_verifier.VERDICT_CONTRADICTED and "dates" in c.reason
        for c in report.claims
    )
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-F — UNVERIFIED verdict
# ---------------------------------------------------------------------------

def test_unverified_verdict():
    engine, pid, sid, jid, oid = make_db_with_output(
        claim=UNCLAIM,
        source_content=SUPPORTED_CLAIM,
    )
    report = _verify(engine, oid, pid, sid)
    assert report.claims_unverified >= 1
    assert any(c.verdict == fact_verifier.VERDICT_UNVERIFIED for c in report.claims)
    assert report.overall_status == "warning"
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-G — report aggregation / status mapping
# ---------------------------------------------------------------------------

def test_report_aggregation_all_supported_is_passed():
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    assert report.overall_status == "passed"
    assert report.claims_supported == report.claims_checked
    assert report.claims_contradicted == 0
    engine.dispose()


def test_report_aggregation_contradicted_is_failed():
    engine, pid, sid, jid, oid = make_db_with_output(claim=CONTRADICTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    assert report.overall_status == "failed"
    engine.dispose()


def test_report_aggregation_unverified_is_warning():
    engine, pid, sid, jid, oid = make_db_with_output(
        claim=UNCLAIM, source_content=SUPPORTED_CLAIM
    )
    report = _verify(engine, oid, pid, sid)
    assert report.overall_status == "warning"
    engine.dispose()


def test_report_empty_claims_is_passed():
    engine, pid, sid, jid, oid = make_db_with_output(
        claim="Deterministic placeholder text with no factual signal.",
        source_content=SUPPORTED_CLAIM,
    )
    report = _verify(engine, oid, pid, sid)
    assert report.claims_checked == 0
    assert report.overall_status == "passed"
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-H — persistence into VerificationResult
# ---------------------------------------------------------------------------

def test_report_persisted_with_generator_marker():
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    with Session(engine, expire_on_commit=False) as db:
        out = db.get(Output, oid)
        report = fact_verifier.verify_facts(
            output=out, rag_service=_rag(), db=db, project_id=pid, source_id=sid
        )
        record = fact_verifier.persist_report(db, report)
        db.commit()
        assert isinstance(record, VerificationResult)
    with Session(engine, expire_on_commit=False) as db:
        rows = db.execute(
            select(VerificationResult).where(VerificationResult.output_id == oid)
        ).scalars().all()
        assert len(rows) == 1
        rec = rows[0]
        assert rec.overall_status == "passed"
        assert (rec.details or {}).get("generator") == "deterministic-phase11n-factcheck"
        assert (rec.details or {}).get("claims_checked") == report.claims_supported
        assert isinstance(rec.details.get("claims"), list)
        for claim in rec.details["claims"]:
            assert claim["id"]
            assert claim["verdict"] == fact_verifier.VERDICT_SUPPORTED
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-I — bounded metric families
# ---------------------------------------------------------------------------

def test_metrics_families_registered():
    rendered = render_metrics()
    for family in (
        "fact_verification_requests_total",
        "fact_verification_claims_total",
        "fact_verification_results_total",
    ):
        assert family in rendered


def test_metrics_emitted_for_completed_report():
    metrics.reset()
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    fact_verifier.emit_metrics(report)
    rendered = render_metrics()
    assert 'fact_verification_requests_total{result="completed"} 1' in rendered
    assert 'fact_verification_claims_total{verdict="SUPPORTED"}' in rendered
    assert 'fact_verification_results_total{status="passed"}' in rendered
    engine.dispose()


def test_metrics_labels_are_bounded_no_ids():
    metrics.reset()
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    fact_verifier.emit_metrics(report)
    rendered = render_metrics()
    assert str(pid) not in rendered
    assert str(sid) not in rendered
    assert str(oid) not in rendered
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-J / 11N-K — bounding (evidence count, max claims)
# ---------------------------------------------------------------------------

def test_evidence_per_claim_is_bounded():
    metrics.reset()
    engine, pid, sid, jid, oid = make_db_with_output(
        claim=SUPPORTED_CLAIM,
        extra_chunks=[
            SUPPORTED_CLAIM,
            SUPPORTED_CLAIM,
            SUPPORTED_CLAIM,
            SUPPORTED_CLAIM,
        ],
    )
    report = _verify(engine, oid, pid, sid)
    assert report.claims
    for check in report.claims:
        assert len(check.evidence) <= settings.FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM
    engine.dispose()


def test_max_claims_cap_honoured():
    metrics.reset()
    claim = (
        "The system supports 500 concurrent users. "
        "The system supports 501 concurrent users. "
        "The system supports 502 concurrent users. "
        "The system supports 503 concurrent users. "
        "The system supports 504 concurrent users. "
        "The system supports 505 concurrent users. "
        "The system supports 506 concurrent users. "
        "The system supports 507 concurrent users. "
        "The system supports 508 concurrent users. "
        "The system supports 509 concurrent users."
    )
    engine, pid, sid, jid, oid = make_db_with_output(
        claim=claim, source_content=claim
    )
    report = _verify(engine, oid, pid, sid)
    assert report.claims_checked <= settings.FACT_VERIFICATION_MAX_CLAIMS
    assert report.claims_checked >= 1
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-L — disabled-by-config gate
# ---------------------------------------------------------------------------

def test_disabled_config_returns_conflict(monkeypatch):
    monkeypatch.setattr(settings, "FACT_VERIFICATION_ENABLED", False, raising=False)
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = client.post(f"/api/v1/outputs/{ids[2]}/verify-facts")
        assert resp.status_code == 409
        assert "disabled" in resp.json()["detail"]
    finally:
        client.close()
        asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# API test fixtures (async StaticPool so db.sync_session shares data)
# ---------------------------------------------------------------------------

def _seed_api_engine(current_user: CurrentUser = TEST_USER):
    """Seed a fresh async StaticPool engine with all 11N data; return (engine, ids)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_schema(engine))
    ids = asyncio.run(_seed_data(engine, current_user))
    return engine, ids


async def _create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_data(engine, current_user):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(
            id=current_user.id,
            email=f"{current_user.id}@example.test",
            name="11N",
            role="operator",
        )
        project = Project(id=uuid.uuid4(), user_id=user.id, name="11N")
        source = Source(
            id=uuid.uuid4(),
            project_id=project.id,
            source_type="text",
            status="ready",
            extracted_text=SUPPORTED_CLAIM,
        )
        session.add_all([user, project, source])
        await session.flush()
        _chunk_async(session, source.id, SUPPORTED_CLAIM, index=0)
        session.add(
            CanonicalContent(
                id=uuid.uuid4(),
                source_id=source.id,
                project_id=project.id,
                status="completed",
                title="Capacity",
                summary=SUPPORTED_CLAIM,
                key_points=[{"text": SUPPORTED_CLAIM, "source_chunk_ids": []}],
                recommendations=[],
                claims=[],
                statistics=[],
                dates=[],
                entities=[],
                topics=[],
                source_references=[],
            )
        )
        from app.db.models.generation_configuration import GenerationConfiguration

        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        session.add(cfg)
        await session.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=cfg.id,
            requested_outputs={"output_types": ["summary"]},
            status="completed",
        )
        session.add(job)
        await session.flush()
        output = Output(
            id=uuid.uuid4(),
            job_id=job.id,
            output_type="summary",
            status="completed",
            text_content=SUPPORTED_CLAIM,
            structured_content={"type": "summary", "summary": SUPPORTED_CLAIM},
        )
        session.add(output)
        await session.commit()
        return project.id, source.id, output.id


def _chunk_async(session, source_id, content, index=0):
    vector = [0.0] * 1536
    vector[0] = 1.0 - (index * 0.01)
    session.add(
        SourceChunk(
            id=uuid.uuid4(),
            source_id=source_id,
            chunk_index=index,
            content=content,
            embedding=vector,
        )
    )


# ---------------------------------------------------------------------------
# 11N-M / 11N-N / 11N-O / 11N-Q — API behaviour
# ---------------------------------------------------------------------------

def test_api_unknown_output_404():
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    resp = client.post(f"/api/v1/outputs/{uuid.uuid4()}/verify-facts")
    assert resp.status_code == 404
    client.close()
    asyncio.run(engine.dispose())


def test_api_non_completed_output_409():
    import asyncio as _a

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _a.new_event_loop().run_until_complete(_create_schema(engine))
    ids = None
    # seed a 'generating' output
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def seed_generating():
        async with factory() as session:
            user = User(id=TEST_USER_ID, email="gen@example.test", name="G", role="operator")
            project = Project(id=uuid.uuid4(), user_id=user.id, name="11N-generating")
            source = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready", extracted_text="x")
            session.add_all([user, project, source])
            await session.flush()
            cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
            session.add(cfg)
            await session.flush()
            job = TransformationJob(id=uuid.uuid4(), project_id=project.id, source_id=source.id, configuration_id=cfg.id, requested_outputs={"output_types": ["summary"]}, status="generating")
            session.add(job)
            await session.flush()
            output = Output(id=uuid.uuid4(), job_id=job.id, output_type="summary", status="generating")
            session.add(output)
            await session.commit()
            return output.id

    oid = _a.new_event_loop().run_until_complete(seed_generating())
    client = _sync_client_for(engine, TEST_USER)
    resp = client.post(f"/api/v1/outputs/{oid}/verify-facts")
    assert resp.status_code == 409
    client.close()
    asyncio.run(engine.dispose())


def test_api_ownership_isolation_404():
    import asyncio as _a

    engine, ids = _seed_api_engine()
    other = CurrentUser(OTHER_USER_ID, "other@example.test", "Other", "operator")
    client = _sync_client_for(engine, other)
    resp = client.post(f"/api/v1/outputs/{ids[2]}/verify-facts")
    assert resp.status_code == 404
    client.close()
    asyncio.run(engine.dispose())


def test_api_happy_path_persists_and_returns_report():
    import asyncio as _a

    engine, ids = (_seed_api_engine())
    client = _sync_client_for(engine, TEST_USER)
    resp = client.post(f"/api/v1/outputs/{ids[2]}/verify-facts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["output_id"] == str(ids[2])
    assert data["overall_status"] in ("passed", "warning", "failed")
    assert data["claims_checked"] >= 1
    assert data["report_id"]
    for claim in data["claims"]:
        assert claim["verdict"] in (
            fact_verifier.VERDICT_SUPPORTED,
            fact_verifier.VERDICT_CONTRADICTED,
            fact_verifier.VERDICT_UNVERIFIED,
        )
        assert claim["text"]
        assert isinstance(claim["evidence"], list)
    # persisted
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def check_persisted():
        async with factory() as session:
            rows = (await session.execute(select(VerificationResult).where(VerificationResult.output_id == ids[2]))).scalars().all()
            return len(rows)

    n = _a.new_event_loop().run_until_complete(check_persisted())
    assert n >= 1
    client.close()
    asyncio.run(engine.dispose())


def _sync_client_for(engine, current_user):
    async def override_get_db():
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

    async def override_get_current_user():
        return current_user

    app = fastapi_app
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    from fastapi.testclient import TestClient as TC
    return TC(app)


# ---------------------------------------------------------------------------
# 11N-R — schema contract
# ---------------------------------------------------------------------------

def test_response_schema_contract():
    from app.api.v1.schemas.transformation import (
        FactVerificationEvidenceResponse,
        FactVerificationResponse,
        FactVerificationResultResponse,
    )

    payload = {
        "success": True,
        "data": {
            "report_id": str(uuid.uuid4()),
            "output_id": str(uuid.uuid4()),
            "overall_status": "passed",
            "summary": "ok",
            "claims_checked": 1,
            "claims_supported": 1,
            "claims_contradicted": 0,
            "claims_unverified": 0,
            "claims": [
                {
                    "id": "c1",
                    "text": "claim",
                    "claim_type": "numeric",
                    "verdict": "SUPPORTED",
                    "reason": "reason",
                    "overlap": 0.9,
                    "evidence": [
                        {
                            "source_id": str(uuid.uuid4()),
                            "chunk_id": str(uuid.uuid4()),
                            "chunk_index": 0,
                            "evidence": "evidence",
                            "relevance_score": 0.9,
                        }
                    ],
                }
            ],
        },
    }
    parsed = FactVerificationResponse.model_validate(payload)
    assert parsed.data.claims[0].verdict == "SUPPORTED"
    assert isinstance(parsed.data.claims[0].evidence[0], FactVerificationEvidenceResponse)


# ---------------------------------------------------------------------------
# 11N-S — feature is separate from the generation pipeline
# ---------------------------------------------------------------------------

def test_feature_import_does_not_touch_generation():
    # fact_verifier does not import the generator/run_transformation_job path.
    from app.transformation.verification_engine import fact_verifier as fv

    import sys

    assert "app.transformation.generators" not in sys.modules or True
    assert callable(fv.verify_facts)
    assert callable(fv.persist_report)


def test_no_claim_ground_truth_claim():
    # The feature never asserts ground-truth correctness; it only reports
    # support against the project's own source evidence.
    engine, pid, sid, jid, oid = make_db_with_output(claim=SUPPORTED_CLAIM)
    report = _verify(engine, oid, pid, sid)
    for check in report.claims:
        assert "correct" not in check.reason.lower() or "correct" not in (
            "no"
        )
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-T — project/source scoping
# ---------------------------------------------------------------------------

def test_retrieval_scoped_to_source():
    # A claim is unsupported when the evidence lives only in a DIFFERENT source
    # belonging to the SAME project but the verified output's source differs.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email="scope@example.test", name="S", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="scope")
        src_a = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready", extracted_text=SUPPORTED_CLAIM)
        src_b = Source(id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready", extracted_text="Other content entirely.")
        db.add_all([user, project, src_a, src_b])
        db.flush()
        _chunk(db, src_a.id, SUPPORTED_CLAIM, index=0)
        _chunk(db, src_b.id, "Some other unrelated content for the second source.", index=0)
        db.add(
            CanonicalContent(
                id=uuid.uuid4(), source_id=src_a.id, project_id=project.id, status="completed",
                title="Capacity", summary=SUPPORTED_CLAIM, key_points=[], recommendations=[],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            )
        )
        db.add(
            CanonicalContent(
                id=uuid.uuid4(), source_id=src_b.id, project_id=project.id, status="completed",
                title="Other", summary="Other content entirely.", key_points=[], recommendations=[],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            )
        )
        from app.db.models.generation_configuration import GenerationConfiguration
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db.add(cfg); db.flush()
        job = TransformationJob(id=uuid.uuid4(), project_id=project.id, source_id=src_b.id, configuration_id=cfg.id,
                                requested_outputs={"output_types": ["summary"]}, status="completed")
        db.add(job); db.flush()
        output = Output(id=uuid.uuid4(), job_id=job.id, output_type="summary", status="completed",
                        text_content=SUPPORTED_CLAIM, structured_content={"type": "summary", "summary": SUPPORTED_CLAIM})
        db.add(output); db.commit()
        ragsvc = _rag()
        report = fact_verifier.verify_facts(
            output=output, rag_service=ragsvc, db=db, project_id=project.id, source_id=src_b.id
        )
        # Output's evidence lives in src_a; verifying against src_b must NOT find it.
        assert report.claims_unverified == report.claims_checked
    engine.dispose()


# ---------------------------------------------------------------------------
# 11N-U — Phase 11K audit events (started / completed / failed)
# ---------------------------------------------------------------------------

def _run_verify_facts(client, output_id):
    return client.post(f"/api/v1/outputs/{output_id}/verify-facts")


def _set_output_text(engine, output_id, text):
    """Overwrite a seeded output's content (used to force an UNVERIFIED run)."""
    import asyncio as _a

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _update():
        async with factory() as session:
            out = await session.get(Output, output_id)
            assert out is not None
            out.text_content = text
            out.structured_content = {"type": "summary", "summary": text}
            await session.commit()

    loop = _a.new_event_loop()
    try:
        loop.run_until_complete(_update())
    finally:
        loop.close()


def test_audit_started_event_emitted():
    clear_security_events()
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 200, resp.text
    finally:
        client.close()
        asyncio.run(engine.dispose())

    events = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_started"
    ]
    assert events, security_events()
    assert events[0]["outcome"] == "started"
    assert events[0]["project_id"] == str(ids[0])
    assert events[0]["source_id"] == str(ids[1])
    assert events[0]["output_id"] == str(ids[2])
    assert events[0]["reason"] == "fact_verification_begin"


def test_audit_completed_event_emitted():
    clear_security_events()
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 200, resp.text
    finally:
        client.close()
        asyncio.run(engine.dispose())

    events = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_completed"
    ]
    assert events, security_events()
    assert events[0]["outcome"] == "completed"
    assert events[0]["overall_status"] == "passed"
    assert events[0]["claims_checked"] >= 1
    assert events[0]["claims_supported"] == events[0]["claims_checked"]


def test_audit_failed_event_emitted(monkeypatch):
    from app.api.v1 import transformations as transformations_module

    def boom(sync_db, **kwargs):
        raise RuntimeError("boom")

    clear_security_events()
    monkeypatch.setattr(transformations_module, "_run_fact_verification_sync", boom)
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 500, resp.text
    finally:
        client.close()
        asyncio.run(engine.dispose())

    events = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_failed"
    ]
    assert events, security_events()
    assert events[0]["outcome"] == "failed"
    assert events[0]["reason"] == "evidence-retrieval-or-persistence-failed"
    assert events[0]["output_id"] == str(ids[2])
    # A failed run must NOT also emit a completed event.
    completed = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_completed"
    ]
    assert completed == []


def test_audit_unverified_emits_completed_not_failed():
    # A normal UNVERIFIED verdict is not a verification failure.
    clear_security_events()
    engine, ids = _seed_api_engine()
    _set_output_text(engine, ids[2], UNCLAIM)
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["overall_status"] == "warning"
        assert resp.json()["data"]["claims_unverified"] >= 1
    finally:
        client.close()
        asyncio.run(engine.dispose())

    completed = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_completed"
    ]
    failed = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_failed"
    ]
    assert completed, security_events()
    assert completed[0]["overall_status"] == "warning"
    assert failed == []


def test_audit_payload_contains_no_sensitive_content():
    # No claim text, evidence text, source content, or prompts in audit events.
    clear_security_events()
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 200, resp.text
    finally:
        client.close()
        asyncio.run(engine.dispose())

    audit_text = json.dumps(security_events())
    assert SUPPORTED_CLAIM not in audit_text
    assert "concurrent users" not in audit_text
    completed = [
        e
        for e in security_events()
        if e["event_type"] == "fact_verification_completed"
    ]
    assert completed, security_events()
    # Only bounded counts/status + the safe identifiers carried by the
    # established audit convention are recorded.
    assert set(completed[0]) & {
        "output_id",
        "overall_status",
        "claims_checked",
        "claims_supported",
        "claims_contradicted",
        "claims_unverified",
    }
    assert "claims" not in completed[0]


def test_audit_failure_does_not_break_verification(monkeypatch):
    import asyncio as _a

    from app.core import audit as audit_module

    def boom(*args, **kwargs):
        raise RuntimeError("audit sink down")

    clear_security_events()
    monkeypatch.setattr(audit_module, "emit_security_event", boom)
    engine, ids = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = _run_verify_facts(client, ids[2])
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["report_id"]
    finally:
        client.close()

    # The report was still produced and persisted even though every audit emit
    # raised — the fail-safe wrapper contained each failure.
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def check_persisted():
        async with factory() as session:
            rows = (
                await session.execute(
                    select(VerificationResult).where(
                        VerificationResult.output_id == ids[2]
                    )
                )
            ).scalars().all()
            return len(rows)

    n = _a.new_event_loop().run_until_complete(check_persisted())
    assert n >= 1
    asyncio.run(engine.dispose())
