"""Phase 8 — Verification Engine tests.

Covers the deterministic Phase 8 verification pipeline: claim extraction,
source-evidence matching, grounding scoring, consistency analysis, warning
generation, result persistence, the verification API, graph integration,
multi-output verification, failure isolation, FakeLLMProvider compatibility,
and fully-offline behavior.

The Phase 8 exit criterion is encoded here: a deliberately altered generated
claim (``50,000`` vs the source's ``500`` concurrent users) MUST be detected as
unsupported.

No API key and no network access are required for any test.
"""

import asyncio
import socket
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import CurrentUser, get_current_user
from app.db.base import Base
from app.db.session import get_db
import app.db.models  # noqa: F401
from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.db.models.verification_result import VerificationResult
from app.ingestion.storage import LocalStorage
from app.main import app as fastapi_app
from app.transformation.service import run_transformation_job
from app.transformation.verification import VerificationHook, run_verification_hook
from app.transformation.verification_engine.claims import extract_claims
from app.transformation.verification_engine.consistency import check_consistency
from app.transformation.verification_engine.engine import run_verification


TEST_USER_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
TEST_USER = CurrentUser(TEST_USER_ID, "phase8@example.test", "Phase 8", "operator")

SOURCE_CAPACITY = "The system supports 500 concurrent users."


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def test_claim_extraction_bullets_numbers_and_declarative():
    output = {
        "type": "summary",
        "text": (
            "- The system supports 500 concurrent users.\n"
            "- 40% of customers renew annually.\n"
            "The engineering team shipped the new platform release on schedule."
        ),
    }
    claims = extract_claims(output)
    texts = {c["text"] for c in claims}
    assert "The system supports 500 concurrent users." in texts
    assert "40% of customers renew annually." in texts
    assert "The engineering team shipped the new platform release on schedule." in texts
    types = {c["claim_type"] for c in claims}
    assert "numeric" in types and "percentage" in types and "factual" in types


def test_claim_extraction_dates_and_structured_shape():
    output = {
        "type": "video",
        "storyboard": [
            {"title": "Scene 1", "description": "Launch is scheduled for 1 March 2024."},
        ],
        "text": "Launch is scheduled for 1 March 2024.",
    }
    claims = extract_claims(output)
    assert claims
    for claim in claims:
        assert claim["id"]
        assert claim["claim_type"] == "date"
        assert isinstance(claim["numbers"], list)
        assert claim["source_position"] is None


def test_claim_extraction_ignores_stylistic_and_placeholder_text():
    output = {
        "type": "presentation",
        "slides": [
            {
                "title": "Slide 1",
                "key_message": "Chart or diagram",
                "supporting_points": ["Deterministic supporting point"],
                "visual_recommendation": "Chart or diagram",
                "speaker_notes": ["Explain: key point"],
            }
        ],
        "text": "Slide 1\nChart or diagram\nDeterministic supporting point",
    }
    assert extract_claims(output) == []


def test_claim_extraction_embeds_entity_from_canonical():
    canonical = {
        "entities": [{"name": "Acme Corporation"}],
        "topics": [],
    }
    output = {
        "type": "advisory",
        "text": "Acme Corporation expanded into the western region.",
        "summary": "Acme Corporation expanded into the western region.",
    }
    claims = extract_claims(output, canonical=canonical)
    assert any("Acme Corporation expanded" in c["text"] for c in claims)


def test_claim_extraction_ignores_embedded_section_headings():
    output = {
        "type": "summary",
        "text": (
            "# Executive Summary: Platform Capacity Report\n"
            f"{SOURCE_CAPACITY}"
        ),
    }
    texts = {c["text"] for c in extract_claims(output)}
    assert texts == {SOURCE_CAPACITY}


# ---------------------------------------------------------------------------
# Source evidence matching / grounding
# ---------------------------------------------------------------------------

def test_evidence_supported_claim_same_sentence():
    result = run_verification(
        output={"type": "summary", "summary": SOURCE_CAPACITY, "text": SOURCE_CAPACITY},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["overall_status"] == "passed"
    assert result["claims_checked"] == 1
    assert result["claims_supported"] == 1
    assert result["grounding_score"] == 1.0
    evidence = result["details"]["evidence"][0]
    assert evidence["verdict"] == "supported"
    assert evidence["chunk_index"] == 0


def test_evidence_unsupported_claim_no_source_match():
    chunks = ["The platform is reliable under peak load conditions."]
    result = run_verification(
        output={
            "type": "summary",
            "text": "The sky is bright blue in the summer months every year.",
        },
        source_chunks=chunks,
    )
    assert result["grounding_score"] == 0.0
    assert result["claims_supported"] == 0
    warning_types = {w["type"] for w in result["warnings"]["items"]}
    assert "unsupported_claim" in warning_types


def test_evidence_weak_support_is_flagged():
    chunks = ["supplier improved scheduling and delivery platform enhancements"]
    result = run_verification(
        output={
            "type": "advisory",
            "text": "The supplier improved on-time delivery performance significantly this quarter.",
        },
        source_chunks=chunks,
    )
    assert result["overall_status"] == "warning"
    record = result["details"]["evidence"][0]
    assert record["verdict"] == "weakly_supported"
    assert record["overlap"] < 0.55
    warning_types = {w["type"] for w in result["warnings"]["items"]}
    assert "weakly_supported_claim" in warning_types


def test_grounding_score_partial_support():
    output_text = (
        f"{SOURCE_CAPACITY}\nThe sky is bright blue in the summer months every year."
    )
    result = run_verification(
        output={"type": "summary", "text": output_text},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["claims_checked"] == 2
    assert result["claims_supported"] == 1
    assert result["grounding_score"] == 0.5
    assert result["overall_status"] == "warning"


def test_grounding_picks_best_chunk_from_many():
    chunks = [
        "The office moved to a new building downtown.",
        "Capacity details are described below.",
        SOURCE_CAPACITY + " Performance scales linearly with hardware.",
    ]
    result = run_verification(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        source_chunks=chunks,
    )
    evidence = result["details"]["evidence"][0]
    assert evidence["verdict"] == "supported"
    assert evidence["chunk_index"] == 2


# ---------------------------------------------------------------------------
# Exit criterion + numeric/date mismatches
# ---------------------------------------------------------------------------

def test_exit_criterion_altered_number_is_detected_unsupported():
    chunks = [SOURCE_CAPACITY]

    supported = run_verification(
        output={"type": "summary", "summary": SOURCE_CAPACITY, "text": SOURCE_CAPACITY},
        source_chunks=chunks,
    )
    assert supported["overall_status"] == "passed"
    assert supported["claims_supported"] == supported["claims_checked"] == 1
    assert supported["grounding_score"] == 1.0

    altered = run_verification(
        output={
            "type": "summary",
            "summary": "The system supports 50,000 concurrent users.",
            "text": "The system supports 50,000 concurrent users.",
        },
        source_chunks=chunks,
    )
    assert altered["overall_status"] == "warning"
    assert altered["claims_supported"] == 0
    assert altered["grounding_score"] == 0.0
    assert altered["details"]["evidence"][0]["verdict"] == "unsupported"
    warning_types = {w["type"] for w in altered["warnings"]["items"]}
    assert "numeric_mismatch" in warning_types


def test_evidence_date_mismatch_is_flagged():
    chunks = ["The release date is 1 March 2025."]
    result = run_verification(
        output={"type": "summary", "text": "The release date is 1 March 2024."},
        source_chunks=chunks,
    )
    assert result["overall_status"] == "warning"
    assert result["claims_supported"] == 0
    assert result["details"]["evidence"][0]["verdict"] == "unsupported"
    assert result["warnings"]["count"] >= 1


# ---------------------------------------------------------------------------
# Consistency checks
# ---------------------------------------------------------------------------

def test_consistency_pass_single_claim():
    result = run_verification(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["consistency_score"] == 1.0
    assert result["details"]["consistency"]["status"] == "passed"
    assert result["details"]["consistency"]["conflicts"] == []


def test_consistency_pass_matching_numbers():
    output_text = (
        f"{SOURCE_CAPACITY}\n"
        "The system supports as many as 500 concurrent users in production."
    )
    result = run_verification(
        output={"type": "summary", "text": output_text},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["consistency_score"] == 1.0
    assert result["details"]["consistency"]["conflicts"] == []


def test_consistency_numeric_conflict_detected():
    output_text = f"{SOURCE_CAPACITY}\nThe system supports 50,000 concurrent users."
    result = run_verification(
        output={"type": "summary", "text": output_text},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["consistency_score"] == 0.5
    conflicts = result["details"]["consistency"]["conflicts"]
    assert any(c["type"] == "conflicting_numbers" for c in conflicts)
    warning_types = {w["type"] for w in result["warnings"]["items"]}
    assert "conflicting_numbers" in warning_types


def test_consistency_date_conflict_detected():
    output_text = (
        "The fiscal year ends on 31 March 2024.\n"
        "The fiscal year ends on 31 March 2025."
    )
    result = run_verification(
        output={"type": "summary", "text": output_text},
        source_chunks=["The fiscal year ends on 31 March 2024."],
    )
    conflicts = result["details"]["consistency"]["conflicts"]
    assert any(c["type"] == "conflicting_dates" for c in conflicts)
    assert result["consistency_score"] < 1.0
    warning_types = {w["type"] for w in result["warnings"]["items"]}
    assert "conflicting_dates" in warning_types


def test_consistency_is_conservative_passes_when_unrelated():
    claims = extract_claims(
        {
            "type": "summary",
            "text": (
                "The system supports 500 concurrent users.\n"
                "The annual budget for the department is 2 million dollars."
            ),
        }
    )
    result = check_consistency(claims)
    assert result["status"] == "passed"
    assert result["conflicts"] == []


# ---------------------------------------------------------------------------
# Zero / empty outputs
# ---------------------------------------------------------------------------

def test_zero_claims_is_safe_and_not_alarming():
    result = run_verification(
        output={"type": "summary", "text": "Nice summary."},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["overall_status"] == "passed"
    assert result["claims_checked"] == 0
    assert result["claims_supported"] == 0
    assert result["grounding_score"] is None
    assert result["consistency_score"] is None
    assert result["warnings"]["count"] == 0


def test_empty_output_is_safe():
    result = run_verification(output={}, source_chunks=[SOURCE_CAPACITY])
    assert result["overall_status"] == "passed"
    assert result["claims_checked"] == 0
    assert result["grounding_score"] is None


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------

def test_verification_result_schema_and_json_safety():
    import json

    result = run_verification(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        source_chunks=[SOURCE_CAPACITY],
    )
    for key in (
        "status", "overall_status", "message", "grounding_score",
        "consistency_score", "claims_checked", "claims_supported",
        "warnings", "details",
    ):
        assert key in result, key
    assert result["status"] == "completed"
    json.dumps(result)  # result must be JSON-serializable for the JSONB columns
    assert result["warnings"]["count"] == len(result["warnings"]["items"])


# ---------------------------------------------------------------------------
# Verification API
# ---------------------------------------------------------------------------

def _make_api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    return engine


async def _init_api_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_verified_output(engine) -> uuid.UUID:
    await _init_api_tables(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(
            id=TEST_USER_ID, email="phase8@example.test", name="Phase 8",
            role="operator",
        )
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 8 API")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text",
            status="ready", extracted_text=SOURCE_CAPACITY,
        )
        config = GenerationConfiguration(
            id=uuid.uuid4(), project_id=project.id, language="English"
        )
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project.id, source_id=source.id,
            configuration_id=config.id,
            requested_outputs={"output_types": ["summary"]},
            status="completed", progress=100,
        )
        output = Output(
            id=uuid.uuid4(), job_id=job.id, output_type="summary",
            status="completed", text_content=SOURCE_CAPACITY,
            structured_content={"type": "summary", "summary": SOURCE_CAPACITY},
        )
        verification = VerificationResult(
            id=uuid.uuid4(), output_id=output.id, overall_status="passed",
            grounding_score=1.0, consistency_score=1.0,
            claims_checked=1, claims_supported=1,
            warnings={"status": "passed", "message": "ok", "items": [], "count": 0},
            details={"status": "completed"},
        )
        session.add_all([user, project, source, config, job, output, verification])
        await session.commit()
        return output.id


def test_verification_api_returns_persisted_record():
    engine = _make_api_engine()
    output_id = asyncio.new_event_loop().run_until_complete(_seed_verified_output(engine))
    asyncio.set_event_loop(None)

    async def override_get_db():
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

    async def override_get_current_user():
        return TEST_USER

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(fastapi_app) as test_client:
            resp = test_client.get(f"/api/v1/outputs/{output_id}/verification")
    finally:
        fastapi_app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["count"] == 1
    record = body["data"][0]
    assert record["output_id"] == str(output_id)
    assert record["overall_status"] == "passed"
    assert record["grounding_score"] == 1.0
    assert record["claims_checked"] == 1


def test_verification_api_404_for_unknown_output():
    engine = _make_api_engine()
    asyncio.new_event_loop().run_until_complete(_init_api_tables(engine))
    asyncio.set_event_loop(None)

    async def override_get_db():
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

    async def override_get_current_user():
        return TEST_USER

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(fastapi_app) as test_client:
            resp = test_client.get(f"/api/v1/outputs/{uuid.uuid4()}/verification")
    finally:
        fastapi_app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Graph integration, multi-output, failure isolation
# ---------------------------------------------------------------------------

def make_grounded_database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(
            id=uuid.uuid4(), email=f"phase8-{uuid.uuid4().hex}@example.test",
            name="P8", role="operator",
        )
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 8")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text",
            status="ready",
            extracted_text=(
                f"{SOURCE_CAPACITY}\nThe platform is highly reliable under load."
            ),
        )
        db.add_all([user, project, source])
        db.flush()
        chunks = [SOURCE_CAPACITY, "The platform is highly reliable under load."]
        for index, content in enumerate(chunks):
            vector = [0.0] * 1536
            vector[0] = 1.0 - (index * 0.1)
            db.add(
                SourceChunk(
                    id=uuid.uuid4(), source_id=source.id, chunk_index=index,
                    content=content, embedding=vector,
                )
            )
        db.add(
            CanonicalContent(
                id=uuid.uuid4(), source_id=source.id, project_id=project.id,
                status="completed",
                title="Platform Capacity Report",
                summary=SOURCE_CAPACITY,
                key_points=[{"text": SOURCE_CAPACITY, "source_chunk_ids": []}],
                recommendations=[
                    {"text": "Monitor capacity weekly", "source_chunk_ids": []}
                ],
                claims=[], statistics=[], dates=[], entities=[], topics=[],
                source_references=[],
            )
        )
        db.commit()
    return engine, project.id, source.id


def make_job(engine, project_id, source_id, output_types, status="queued"):
    with Session(engine, expire_on_commit=False) as db:
        config = GenerationConfiguration(
            id=uuid.uuid4(), project_id=project_id, language="English"
        )
        db.add(config)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=config.id,
            requested_outputs={"output_types": output_types},
            status=status,
        )
        db.add(job)
        db.commit()
        return job.id


def test_graph_integration_verifies_and_persists_real_result():
    engine, project_id, source_id = make_grounded_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as session:
        result = run_transformation_job(session, job_id)
    assert result["outputs_completed"] == 1
    with Session(engine) as session:
        records = session.execute(select(VerificationResult)).scalars().all()
        assert len(records) == 1
        record = records[0]
        assert record.details["status"] == "completed"
        assert record.overall_status == "passed"
        assert record.claims_checked == 1
        assert record.claims_supported == 1
        assert record.grounding_score == 1.0
        assert record.warnings["count"] == 0
        output = session.execute(select(Output)).scalars().one()
        assert output.status == "completed"
    engine.dispose()


def test_multi_output_produces_independent_verifications(tmp_path):
    engine, project_id, source_id = make_grounded_database()
    output_types = [
        "summary", "linkedin", "x", "advisory",
        "infographic", "presentation", "video",
    ]
    job_id = make_job(engine, project_id, source_id, output_types)
    with Session(engine) as session:
        result = run_transformation_job(
            session, job_id,
            storage=LocalStorage(str(tmp_path / "phase8-artifacts")),
        )
    assert result["outputs_completed"] == 7
    with Session(engine) as session:
        outputs = session.execute(
            select(Output).order_by(Output.created_at)
        ).scalars().all()
        assert len(outputs) == 7
        records = session.execute(select(VerificationResult)).scalars().all()
        assert len(records) == 7
        by_output = {str(r.output_id): r for r in records}
        for output in outputs:
            assert output.status == "completed"
            record = by_output[str(output.id)]
            assert record.output_id == output.id
            assert record.details["status"] == "completed"
    engine.dispose()


class ExplodingVerificationHook:
    """Simulates an unexpected verification-engine crash."""

    def verify(self, **kwargs):
        raise RuntimeError("simulated verification crash")


def test_verification_failure_isolated_output_survives():
    engine, project_id, source_id = make_grounded_database()
    job_id = make_job(engine, project_id, source_id, ["summary"])
    with Session(engine) as session:
        result = run_transformation_job(
            session, job_id, verification_hook=ExplodingVerificationHook()
        )
    assert result["outputs_completed"] == 1
    with Session(engine) as session:
        job = session.get(TransformationJob, job_id)
        assert job.status == "completed"
        output = session.execute(select(Output)).scalars().one()
        assert output.status == "completed"
        records = session.execute(select(VerificationResult)).scalars().all()
        assert len(records) == 1
        assert records[0].overall_status == "warning"
        assert records[0].details["status"] == "error"
    engine.dispose()


# ---------------------------------------------------------------------------
# Determinism, no-network, FakeLLMProvider compatibility
# ---------------------------------------------------------------------------

def test_deterministic_repeatable_results():
    output = {"type": "summary", "text": SOURCE_CAPACITY}
    chunks = [SOURCE_CAPACITY]
    first = run_verification(output=output, source_chunks=chunks)
    second = run_verification(output=output, source_chunks=chunks)
    assert first == second


def test_no_network_calls_during_verification(monkeypatch):
    def deny_any_socket(*args, **kwargs):
        raise AssertionError("verification attempted a network call")

    monkeypatch.setattr(socket, "socket", deny_any_socket)
    result = run_verification(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["overall_status"] == "passed"


def test_fake_llm_provider_output_verifiable_offline():
    from app.transformation.generators import get_generator
    from app.transformation.llm.fake import FakeLLMProvider

    canonical = {
        "title": "Capacity Report",
        "summary": SOURCE_CAPACITY,
        "key_points": [{"text": SOURCE_CAPACITY, "source_chunk_ids": []}],
        "recommendations": [],
        "topics": [], "entities": [], "claims": [], "statistics": [],
        "dates": [], "source_references": [],
    }
    generator = get_generator("summary", llm_provider=FakeLLMProvider())
    generated = generator.generate(canonical=canonical, config={}, rag_context=None)
    result = run_verification(
        output=generated,
        canonical=canonical,
        source_chunks=[SOURCE_CAPACITY],
    )
    assert result["details"]["status"] == "completed"
    assert result["claims_checked"] >= 1
    assert result["claims_supported"] >= 1
    assert result["grounding_score"] > 0.0


# ---------------------------------------------------------------------------
# Phase 6 hook contract preserved
# ---------------------------------------------------------------------------

def test_phase6_hook_contract_preserved():
    result = run_verification_hook(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        canonical={"title": "Capacity Report"},
        source_chunks=[SOURCE_CAPACITY],
    )
    for key in (
        "output_type", "status", "overall_status", "message",
        "grounding_score", "consistency_score", "claims_checked",
        "claims_supported", "warnings", "details",
    ):
        assert key in result, key
    assert result["output_type"] == "summary"
    assert result["status"] == "completed"
    assert result["overall_status"] in {"passed", "warning"}


def test_hook_runs_without_explicit_source_chunks():
    result = run_verification_hook(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        canonical={},
    )
    assert result["status"] == "completed"
    assert result["claims_checked"] == 1
    assert result["overall_status"] == "warning"


def test_verification_hook_instance_carries_source_chunks():
    hook = VerificationHook(source_chunks=[SOURCE_CAPACITY])
    result = hook.verify(
        output={"type": "summary", "text": SOURCE_CAPACITY},
        canonical={},
    )
    assert result["overall_status"] == "passed"
    assert result["grounding_score"] == 1.0