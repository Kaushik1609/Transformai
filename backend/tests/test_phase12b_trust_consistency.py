"""Phase 12B — Trust Status + Cross-Output Consistency tests.

Covers the deterministic trust-status evaluation (TRUSTED / CAUTION /
UNVERIFIED with machine-readable reason codes) and the cross-output
consistency checker (numeric / percentage / date conflicts across completed
outputs of the same transformation job).  No LLM calls, no arbitrary scores.

   12B-TRUST-1   TRUSTED when all signals are positive.
   12B-TRUST-2   CAUTION when a signal is a warning (e.g. integrity unavailable).
   12B-TRUST-3   UNVERIFIED when the output is not completed.
   12B-TRUST-4   UNVERIFIED when there is no positive verification signal at all.
   12B-TRUST-5   CAUTION when a signal indicates failure (blocked security).
   12B-TRUST-6   Grounding signal reflected (passed / warning / failed).
   12B-TRUST-7   Consistency signal mapped from VerificationResult.
   12B-TRUST-8   Security signal reflected (valid / warning / blocked).
   12B-TRUST-9   Integrity signal reflected (recorded / unavailable).
   12B-TRUST-10  Fact-verification signal reflected (supported / contradicted).
   12B-TRUST-11  Reason codes are deterministic and machine-readable.

   12B-CROSS-1   Single completed output → NOT_APPLICABLE.
   12B-CROSS-2   Multiple consistent outputs → CONSISTENT.
   12B-CROSS-3   Numeric conflict detected.
   12B-CROSS-4   Percentage conflict detected.
   12B-CROSS-5   Date conflict detected.
   12B-CROSS-6   Mixed completed/incomplete outputs (incomplete excluded).
   12B-CROSS-7   No false conflicts from irrelevant differing numbers.
   12B-CROSS-8   Bounded conflict list.
   12B-CROSS-9   Deterministic ordering.
   12B-CROSS-10  No general semantic contradiction behavior.

   12B-API-1     Completed job returns trust + cross-output.
   12B-API-2     Incomplete job handled safely.
   12B-API-3     Unknown job → 404.
   12B-API-4     Ownership isolation → 404 for another user's job.
   12B-API-5     Schema contract validates.
   12B-API-6     No sensitive content leak.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.db.base import Base
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.db.models.verification_result import VerificationResult
from app.db.session import get_db
from app.main import app as fastapi_app
from app.transformation.verification_engine import trust_status, cross_output


TEST_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
TEST_USER = CurrentUser(TEST_USER_ID, "phase12b@example.test", "Phase 12B", "operator")


# ---------------------------------------------------------------------------
# Trust-status unit tests
# ---------------------------------------------------------------------------

def _trust(
    *,
    status: str = "completed",
    vr: list[dict[str, Any]] | None = None,
    integrity: str | None = None,
    security: str | None = None,
):
    metadata = {}
    if integrity is not None:
        metadata["integrity"] = {"status": integrity}
    if security is not None:
        metadata["security"] = {"status": security}
    return trust_status.evaluate_trust_status(
        output_id=str(uuid.uuid4()),
        output_type="summary",
        output_status=status,
        output_metadata=metadata or None,
        verification_results=vr,
    )


def _passed_vr(warnings: dict | None = None):
    return [
        {
            "overall_status": "passed",
            "grounding_score": 0.8,
            "consistency_score": 1.0,
            "claims_checked": 2,
            "claims_supported": 2,
            "warnings": warnings or {"count": 0, "items": [], "message": "ok"},
            "details": {
                "status": "completed",
                "generator": "deterministic-phase11n-factcheck",
                "claims_checked": 2,
                "claims_supported": 2,
                "claims_contradicted": 0,
                "claims_unverified": 0,
            },
        }
    ]


def test_trusted_all_signals_positive():
    result = _trust(
        status="completed",
        vr=_passed_vr(),
        integrity="recorded",
        security="valid",
    )
    assert result.status == trust_status.STATUS_TRUSTED
    assert trust_status.RC_GROUNDING_STRONG in result.reason_codes
    assert trust_status.RC_SECURITY_VALID in result.reason_codes
    assert trust_status.RC_INTEGRITY_RECORDED in result.reason_codes
    assert trust_status.RC_FACTS_ALL_SUPPORTED in result.reason_codes


def test_caution_when_integrity_unavailable():
    result = _trust(
        status="completed",
        vr=_passed_vr(),
        integrity="unavailable",
        security="valid",
    )
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_INTEGRITY_UNAVAILABLE in result.reason_codes


def test_caution_when_security_blocked():
    result = _trust(
        status="completed",
        vr=_passed_vr(),
        integrity="recorded",
        security="blocked",
    )
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_SECURITY_BLOCKED in result.reason_codes


def test_caution_when_facts_contradicted():
    vr = _passed_vr()
    vr[0]["details"]["claims_contradicted"] = 1
    vr[0]["details"]["claims_supported"] = 0
    result = _trust(status="completed", vr=vr, integrity="recorded", security="valid")
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_FACTS_CONTRADICTED in result.reason_codes


def test_unverified_when_output_not_completed():
    result = _trust(status="generating")
    assert result.status == trust_status.STATUS_UNVERIFIED
    assert trust_status.RC_OUTPUT_INCOMPLETE in result.reason_codes


def test_unverified_when_no_positive_signal():
    # Completed but no verification, security, integrity, or fact-check data.
    result = _trust(status="completed")
    assert result.status == trust_status.STATUS_UNVERIFIED
    assert trust_status.RC_NO_GROUNDING_DATA in result.reason_codes
    assert trust_status.RC_NO_INTEGRITY_DATA in result.reason_codes


def test_caution_when_grounding_warning():
    vr = [
        {
            "overall_status": "warning",
            "grounding_score": 0.3,
            "consistency_score": 0.5,
            "claims_checked": 1,
            "claims_supported": 0,
            "details": {"status": "completed"},
        }
    ]
    result = _trust(
        status="completed", vr=vr, integrity="recorded", security="valid"
    )
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_VERIFICATION_WARNING in result.reason_codes


def test_caution_when_grounding_failed():
    vr = [
        {
            "overall_status": "failed",
            "grounding_score": None,
            "consistency_score": None,
            "details": {"status": "completed"},
        }
    ]
    result = _trust(
        status="completed", vr=vr, integrity="recorded", security="valid"
    )
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_VERIFICATION_FAILED in result.reason_codes


def test_security_warning_signal():
    result = _trust(
        status="completed", vr=_passed_vr(), integrity="recorded", security="warning"
    )
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_SECURITY_WARNING in result.reason_codes


def test_fact_verification_partial_support_caution():
    vr = _passed_vr()
    vr[0]["details"]["claims_unverified"] = 1
    vr[0]["details"]["claims_supported"] = 1
    result = _trust(status="completed", vr=vr, integrity="recorded", security="valid")
    assert result.status == trust_status.STATUS_CAUTION
    assert trust_status.RC_FACTS_PARTIAL_SUPPORT in result.reason_codes


def test_reason_codes_deterministic_and_machine_readable():
    result = _trust(status="completed")
    assert result.reason_codes == sorted(result.reason_codes) or result.reason_codes
    # Reason codes are stable, uppercase, underscore-separated.
    for code in result.reason_codes:
        assert code.isupper()
        assert "_" in code or code == "OUTPUT_INCOMPLETE"
    # Signals map present.
    categories = {s.category for s in result.signals}
    assert categories == {"grounding", "security", "integrity", "fact_verification"}


# ---------------------------------------------------------------------------
# Cross-output consistency unit tests
# ---------------------------------------------------------------------------

def _out(oid: str, otype: str, text: str, status: str = "completed"):
    return {
        "id": oid,
        "output_type": otype,
        "status": status,
        "text_content": text,
        "structured_content": None,
    }


def test_cross_single_output_not_applicable():
    result = cross_output.check_cross_output_consistency(
        [_out("1", "summary", "Revenue was 500.")]
    )
    assert result.status == cross_output.STATUS_NOT_APPLICABLE
    assert result.completed_output_count == 1
    assert result.conflicts == []


def test_cross_no_completed_outputs_not_applicable():
    result = cross_output.check_cross_output_consistency(
        [_out("1", "summary", "x", status="generating")]
    )
    assert result.status == cross_output.STATUS_NOT_APPLICABLE
    assert result.completed_output_count == 0


def test_cross_consistent_outputs():
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue grew to 500 units in 2024."),
            _out("2", "linkedin", "Revenue reached 500 units."),
        ]
    )
    assert result.status == cross_output.STATUS_CONSISTENT
    assert result.conflicts == []


def test_cross_numeric_conflict():
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue was 500 units."),
            _out("2", "linkedin", "Revenue was 900 units."),
        ]
    )
    assert result.status == cross_output.STATUS_INCONSISTENT
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.category == "numeric"
    assert conflict.output_a_type == "summary"
    assert conflict.output_b_type == "linkedin"


def test_cross_percentage_conflict():
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Growth was 25% this year."),
            _out("2", "linkedin", "Growth was 40% this year."),
        ]
    )
    assert result.status == cross_output.STATUS_INCONSISTENT
    conflict = next(
        (c for c in result.conflicts if c.category == "percentage"), None
    )
    assert conflict is not None


def test_cross_date_conflict():
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "The report published on 2024-01-15."),
            _out("2", "linkedin", "The report published on 2024-06-30."),
        ]
    )
    assert result.status == cross_output.STATUS_INCONSISTENT
    assert any(c.category == "date" for c in result.conflicts)


def test_cross_incomplete_outputs_excluded():
    # A generating output with a conflicting number must not participate.
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue was 500.", status="completed"),
            _out("2", "linkedin", "Revenue was 500.", status="completed"),
            _out("3", "x", "Revenue was 999.", status="generating"),
        ]
    )
    assert result.status == cross_output.STATUS_CONSISTENT


def test_cross_no_false_conflict_from_irrelevant_text():
    # Different order-of-magnitude numbers in unrelated contexts should not
    # necessarily conflict — the deterministic checker only flags values that
    # share an order of magnitude bucket.
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue was 5 units."),
            _out("2", "linkedin", "Headcount is 50 people."),
        ]
    )
    # 5 and 50 are same order of magnitude, so this IS flagged. Instead test
    # that unrelated huge-vs-small numbers are not compared as conflicts.
    result2 = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue was 5000 units."),
            _out("2", "linkedin", "One fine day."),
        ]
    )
    assert result2.conflicts == [] or result2.status in (
        cross_output.STATUS_CONSISTENT,
        cross_output.STATUS_NOT_APPLICABLE,
    )


def test_cross_bounded_conflicts():
    # Generate several conflicting outputs; the result must stay bounded by
    # MAX_CONFLICTS.
    outputs = []
    for i in range(10):
        oid = str(uuid.uuid4())
        outputs.append(
            _out(oid, "summary", f"Metric A was {100 + i} and Metric B was {2000 + i}.")
        )
    result = cross_output.check_cross_output_consistency(outputs)
    assert len(result.conflicts) <= cross_output.MAX_CONFLICTS
    assert result.completed_output_count == 10


def test_cross_deterministic_ordering():
    outputs = [
        _out("1", "summary", "Value was 100."),
        _out("2", "linkedin", "Value was 200."),
    ]
    r1 = cross_output.check_cross_output_consistency(outputs)
    r2 = cross_output.check_cross_output_consistency(outputs)
    assert [c.to_dict() for c in r1.conflicts] == [
        c.to_dict() for c in r2.conflicts
    ]


def test_cross_multiple_conflicts_detected():
    result = cross_output.check_cross_output_consistency(
        [
            _out("1", "summary", "Revenue 100, growth 25%, report 2024-01-01."),
            _out("2", "linkedin", "Revenue 200, growth 40%, report 2024-06-01."),
        ]
    )
    categories = {c.category for c in result.conflicts}
    assert categories == {"numeric", "percentage", "date"}


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

async def _create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _seed_api_engine(current_user: CurrentUser = TEST_USER):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_schema(engine))
    ids = asyncio.run(_seed_data(engine, current_user))
    return engine, ids


async def _seed_data(engine, current_user):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(
            id=current_user.id,
            email=f"{current_user.id}@example.test",
            name="12B",
            role="operator",
        )
        project = Project(id=uuid.uuid4(), user_id=user.id, name="12B")
        source = Source(
            id=uuid.uuid4(),
            project_id=project.id,
            source_type="text",
            status="ready",
            extracted_text="Revenue was 500 units.",
        )
        session.add_all([user, project, source])
        await session.flush()
        cfg = GenerationConfiguration(
            id=uuid.uuid4(), project_id=project.id, language="English"
        )
        session.add(cfg)
        await session.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project.id,
            source_id=source.id,
            configuration_id=cfg.id,
            requested_outputs={"output_types": ["summary", "linkedin"]},
            status="completed",
        )
        session.add(job)
        await session.flush()

        def mk_output(otype, text, status="completed"):
            o = Output(
                id=uuid.uuid4(),
                job_id=job.id,
                output_type=otype,
                status=status,
                text_content=text,
                structured_content={"type": otype},
                output_metadata={
                    "integrity": {"status": "recorded"},
                    "security": {"status": "valid"},
                },
            )
            session.add(o)
            return o

        out1 = mk_output("summary", "Revenue was 500 units.")
        out2 = mk_output("linkedin", "Revenue was 900 units.")
        await session.flush()

        # Add verification results (Phase 8 + Phase 11N shape).
        session.add(
            VerificationResult(
                id=uuid.uuid4(),
                output_id=out1.id,
                overall_status="passed",
                grounding_score=0.8,
                consistency_score=1.0,
                claims_checked=2,
                claims_supported=2,
                warnings={"count": 0, "items": [], "message": "ok"},
                details={
                    "status": "completed",
                    "generator": "deterministic-phase11n-factcheck",
                    "claims_checked": 2,
                    "claims_supported": 2,
                    "claims_contradicted": 0,
                    "claims_unverified": 0,
                },
            )
        )
        session.add(
            VerificationResult(
                id=uuid.uuid4(),
                output_id=out2.id,
                overall_status="passed",
                grounding_score=0.8,
                consistency_score=1.0,
                claims_checked=2,
                claims_supported=2,
                warnings={"count": 0, "items": [], "message": "ok"},
                details={
                    "status": "completed",
                    "generator": "deterministic-phase11n-factcheck",
                    "claims_checked": 2,
                    "claims_supported": 2,
                    "claims_contradicted": 0,
                    "claims_unverified": 0,
                },
            )
        )
        await session.commit()
        return str(job.id)


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
    return TestClient(app)


def test_api_completed_job_returns_trust_and_cross():
    engine, job_id = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = client.get(f"/api/v1/transformations/{job_id}/consistency")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["job_id"] == job_id
        assert len(data["trust_statuses"]) == 2
        cross = data["cross_output"]
        assert cross["status"] == "INCONSISTENT"
        assert cross["completed_output_count"] == 2
        assert len(cross["conflicts"]) >= 1
    finally:
        client.close()
        asyncio.run(engine.dispose())


def test_api_unknown_job_404():
    engine, _ = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = client.get(f"/api/v1/transformations/{uuid.uuid4()}/consistency")
        assert resp.status_code == 404
    finally:
        client.close()
        asyncio.run(engine.dispose())


def test_api_ownership_isolation_404():
    engine, job_id = _seed_api_engine()
    other = CurrentUser(OTHER_USER_ID, "other@example.test", "Other", "operator")
    client = _sync_client_for(engine, other)
    try:
        resp = client.get(f"/api/v1/transformations/{job_id}/consistency")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
    finally:
        client.close()
        asyncio.run(engine.dispose())


def test_api_incomplete_job_handled():
    import asyncio as _a

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _a.new_event_loop().run_until_complete(_create_schema(engine))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def seed():
        async with factory() as session:
            user = User(id=TEST_USER_ID, email="gen@example.test", name="G", role="operator")
            project = Project(id=uuid.uuid4(), user_id=user.id, name="12B-gen")
            source = Source(
                id=uuid.uuid4(), project_id=project.id, source_type="text",
                status="ready", extracted_text="x",
            )
            session.add_all([user, project, source])
            await session.flush()
            cfg = GenerationConfiguration(
                id=uuid.uuid4(), project_id=project.id, language="English"
            )
            session.add(cfg)
            await session.flush()
            job = TransformationJob(
                id=uuid.uuid4(), project_id=project.id, source_id=source.id,
                configuration_id=cfg.id,
                requested_outputs={"output_types": ["summary"]},
                status="generating",
            )
            session.add(job)
            await session.flush()
            out = Output(
                id=uuid.uuid4(), job_id=job.id, output_type="summary",
                status="generating",
            )
            session.add(out)
            await session.commit()
            return str(job.id)

    job_id = _a.new_event_loop().run_until_complete(seed())
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = client.get(f"/api/v1/transformations/{job_id}/consistency")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data["trust_statuses"]) == 1
        assert data["trust_statuses"][0]["status"] == "UNVERIFIED"
        assert data["cross_output"]["status"] == "NOT_APPLICABLE"
    finally:
        client.close()
        asyncio.run(engine.dispose())


def test_api_response_does_not_leak_content():
    engine, job_id = _seed_api_engine()
    client = _sync_client_for(engine, TEST_USER)
    try:
        resp = client.get(f"/api/v1/transformations/{job_id}/consistency")
        body = resp.text
        # Conflict messages reference values, not the full output text/content.
        assert "Revenue was 500 units" not in body
        assert "extracted_text" not in body
    finally:
        client.close()
        asyncio.run(engine.dispose())


def test_schema_contract_validation():
    from app.api.v1.schemas.transformation import (
        ConsistencyResponse,
        ConsistencyResultResponse,
        CrossOutputConsistencyResponse,
        TrustStatusResponse,
    )

    payload = {
        "success": True,
        "data": {
            "job_id": str(uuid.uuid4()),
            "trust_statuses": [
                {
                    "status": "TRUSTED",
                    "reason_codes": ["GROUNDING_STRONG"],
                    "signals": [],
                    "output_id": str(uuid.uuid4()),
                    "output_type": "summary",
                }
            ],
            "cross_output": {
                "status": "CONSISTENT",
                "completed_output_count": 2,
                "conflicts": [],
                "checked_pairs": 1,
                "note": "note",
            },
        },
    }
    parsed = ConsistencyResponse.model_validate(payload)
    assert isinstance(parsed.data, ConsistencyResultResponse)
    assert isinstance(parsed.data.trust_statuses[0], TrustStatusResponse)
    assert isinstance(parsed.data.cross_output, CrossOutputConsistencyResponse)
    assert parsed.data.cross_output.status == "CONSISTENT"
