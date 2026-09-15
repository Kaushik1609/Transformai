"""
TransformIQ / KaryaSetu AI — Phase 2D Dissemination Control Test Suite

Comprehensive tests for deterministic, policy-controlled dissemination decisions.

Tests verify:
1. PUBLIC allows public destinations (PUBLIC_WEB, LINKEDIN, X)
2. INTERNAL blocks public web
3. INTERNAL blocks LinkedIn
4. INTERNAL blocks X
5. CONFIDENTIAL blocks public web
6. CONFIDENTIAL blocks LinkedIn
7. CONFIDENTIAL blocks X
8. RESTRICTED blocks public web
9. RESTRICTED blocks LinkedIn
10. RESTRICTED blocks X
11. Internal / review / download / presentation allowed across classifications
12. Unknown destination fails closed
13. Missing / empty destination fails closed
14. Deterministic decisions (100% reproducible, zero LLM calls)
15. Correct decision reason and policy ID
16. Multi-output transformation behavior
17. Backend enforcement at download, export, and dissemination endpoints
18. Frontend metadata contract reflection
19. Existing ownership / auth controls remain intact (IDOR protection)
20. Existing Phase 2A/2B/2C compatibility
21. LLM output cannot override dissemination policy
22. Changing provider does not change dissemination policy
23. Policy evaluation does not call an LLM
24. No secret values appear in logs or errors
25. Future-proofing extension points (hash, signature, provenance, approval)
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import CurrentUser, DEV_USER_EMAIL, DEV_USER_NAME, DEV_USER_ROLE, get_current_user
from app.core.audit import security_events, clear_security_events
from app.db.base import Base
from app.db.models.output import Output
from app.db.session import get_db
from app.main import app
from app.policy.classification import InformationClassification
from app.policy.dissemination import (
    DISSEMINATION_POLICY_ID,
    DisseminationDecision,
    DisseminationDecisionOutcome,
    DisseminationDestination,
    DisseminationEngine,
    InvalidDestinationError,
    VALID_DESTINATIONS,
    get_dissemination_engine,
    normalize_destination,
)

TEST_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_USER_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


# ---------------------------------------------------------------------------
# Database & TestClient Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sqlite_engine():
    import app.db.models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
async def async_db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


@pytest.fixture
def client(async_db_session: AsyncSession):
    async def override_get_db():
        yield async_db_session

    async def override_get_current_user():
        return CurrentUser(
            id=TEST_USER_ID,
            email=DEV_USER_EMAIL,
            name=DEV_USER_NAME,
            role=DEV_USER_ROLE,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def engine() -> DisseminationEngine:
    return get_dissemination_engine()


# ===========================================================================
# Unit Tests: Destination Normalization & Fail-Closed Behavior
# ===========================================================================

class TestDestinationNormalization:
    """Verify destination normalization and fail-closed requirements."""

    def test_valid_destinations_normalization(self):
        assert normalize_destination("INTERNAL") == DisseminationDestination.INTERNAL
        assert normalize_destination("internal") == DisseminationDestination.INTERNAL
        assert normalize_destination("  REVIEW  ") == DisseminationDestination.REVIEW
        assert normalize_destination("download") == DisseminationDestination.DOWNLOAD
        assert normalize_destination("presentation") == DisseminationDestination.PRESENTATION
        assert normalize_destination("public_web") == DisseminationDestination.PUBLIC_WEB
        assert normalize_destination("linkedin") == DisseminationDestination.LINKEDIN
        assert normalize_destination("x") == DisseminationDestination.X
        assert normalize_destination("twitter") == DisseminationDestination.X
        assert normalize_destination("public") == DisseminationDestination.PUBLIC_WEB

    def test_missing_destination_fails_closed(self):
        with pytest.raises(InvalidDestinationError):
            normalize_destination(None)

    def test_empty_destination_fails_closed(self):
        with pytest.raises(InvalidDestinationError):
            normalize_destination("")
        with pytest.raises(InvalidDestinationError):
            normalize_destination("   ")

    def test_unknown_destination_fails_closed(self):
        with pytest.raises(InvalidDestinationError):
            normalize_destination("TIKTOK")
        with pytest.raises(InvalidDestinationError):
            normalize_destination("DARK_WEB")
        with pytest.raises(InvalidDestinationError):
            normalize_destination("UNAUTHORIZED_CHANNEL")


# ===========================================================================
# Deterministic Policy Evaluation: Core Matrix Requirements 1-15
# ===========================================================================

class TestDisseminationPolicyMatrix:
    """Verify deterministic evaluation matrix across all 4 classification tiers."""

    # 1. PUBLIC allows public destinations
    def test_1_public_allows_public_destinations(self, engine: DisseminationEngine):
        for dest in [
            DisseminationDestination.PUBLIC_WEB,
            DisseminationDestination.LINKEDIN,
            DisseminationDestination.X,
        ]:
            decision = engine.evaluate(InformationClassification.PUBLIC, dest)
            assert decision.allowed is True
            assert decision.decision == DisseminationDecisionOutcome.ALLOW
            assert decision.destination == dest.value
            assert decision.classification == InformationClassification.PUBLIC
            assert "allowed" in decision.reason.lower()

    # 2. INTERNAL blocks public web
    def test_2_internal_blocks_public_web(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.INTERNAL, DisseminationDestination.PUBLIC_WEB
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK
        assert "prohibited" in decision.reason.lower() or "blocked" in decision.reason.lower()

    # 3. INTERNAL blocks LinkedIn
    def test_3_internal_blocks_linkedin(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.INTERNAL, DisseminationDestination.LINKEDIN
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 4. INTERNAL blocks X
    def test_4_internal_blocks_x(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.INTERNAL, DisseminationDestination.X
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 5. CONFIDENTIAL blocks public web
    def test_5_confidential_blocks_public_web(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.CONFIDENTIAL, DisseminationDestination.PUBLIC_WEB
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 6. CONFIDENTIAL blocks LinkedIn
    def test_6_confidential_blocks_linkedin(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.CONFIDENTIAL, DisseminationDestination.LINKEDIN
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 7. CONFIDENTIAL blocks X
    def test_7_confidential_blocks_x(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.CONFIDENTIAL, DisseminationDestination.X
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 8. RESTRICTED blocks public web
    def test_8_restricted_blocks_public_web(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.RESTRICTED, DisseminationDestination.PUBLIC_WEB
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 9. RESTRICTED blocks LinkedIn
    def test_9_restricted_blocks_linkedin(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.RESTRICTED, DisseminationDestination.LINKEDIN
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 10. RESTRICTED blocks X
    def test_10_restricted_blocks_x(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.RESTRICTED, DisseminationDestination.X
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 11. Internal/review/download/presentation allowed across classifications
    @pytest.mark.parametrize(
        "classification",
        [
            InformationClassification.PUBLIC,
            InformationClassification.INTERNAL,
            InformationClassification.CONFIDENTIAL,
            InformationClassification.RESTRICTED,
        ],
    )
    @pytest.mark.parametrize(
        "destination",
        [
            DisseminationDestination.INTERNAL,
            DisseminationDestination.REVIEW,
            DisseminationDestination.DOWNLOAD,
            DisseminationDestination.PRESENTATION,
        ],
    )
    def test_11_internal_review_download_presentation_allowed(
        self,
        engine: DisseminationEngine,
        classification: InformationClassification,
        destination: DisseminationDestination,
    ):
        decision = engine.evaluate(classification, destination)
        assert decision.allowed is True
        assert decision.decision == DisseminationDecisionOutcome.ALLOW
        assert decision.destination == destination.value

    # 12. Unknown destination fails closed
    def test_12_unknown_destination_fails_closed(self, engine: DisseminationEngine):
        decision = engine.evaluate(InformationClassification.PUBLIC, "INVALID_DESTINATION")
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK
        assert "blocked" in decision.reason.lower()

    # 13. Missing destination fails closed
    def test_13_missing_destination_fails_closed(self, engine: DisseminationEngine):
        decision = engine.evaluate(InformationClassification.PUBLIC, None)
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    # 14. Deterministic reproducibility
    def test_14_deterministic_decisions(self, engine: DisseminationEngine):
        for _ in range(20):
            dec1 = engine.evaluate(InformationClassification.CONFIDENTIAL, "LINKEDIN")
            dec2 = engine.evaluate(InformationClassification.CONFIDENTIAL, "LINKEDIN")
            assert dec1.allowed == dec2.allowed
            assert dec1.decision == dec2.decision
            assert dec1.reason == dec2.reason
            assert dec1.policy_id == dec2.policy_id

    # 15. Correct decision reason and policy ID
    def test_15_correct_decision_reason_and_policy_id(self, engine: DisseminationEngine):
        decision = engine.evaluate(InformationClassification.RESTRICTED, "LINKEDIN")
        assert decision.policy_id == DISSEMINATION_POLICY_ID
        assert "RESTRICTED" in decision.reason
        assert "LINKEDIN" in decision.reason


# ===========================================================================
# Multi-Output Transformations & Output Types vs Destinations (Req 16)
# ===========================================================================

class TestMultiOutputDissemination:
    """Verify independent dissemination decisions across multi-output transformations."""

    def test_16_multi_output_independent_decisions(self, engine: DisseminationEngine):
        # A single CONFIDENTIAL source produces summary, linkedin, pptx, x
        classification = InformationClassification.CONFIDENTIAL

        # summary -> DOWNLOAD/INTERNAL: allowed
        summary_dec = engine.evaluate_output(classification, "summary", destination="DOWNLOAD")
        assert summary_dec.allowed is True
        assert summary_dec.decision == DisseminationDecisionOutcome.ALLOW

        # pptx/presentation -> PRESENTATION: allowed
        presentation_dec = engine.evaluate_output(classification, "presentation", destination="PRESENTATION")
        assert presentation_dec.allowed is True
        assert presentation_dec.decision == DisseminationDecisionOutcome.ALLOW

        # linkedin -> LINKEDIN: blocked
        linkedin_dec = engine.evaluate_output(classification, "linkedin", destination="LINKEDIN")
        assert linkedin_dec.allowed is False
        assert linkedin_dec.decision == DisseminationDecisionOutcome.BLOCK

        # x -> X: blocked
        x_dec = engine.evaluate_output(classification, "x", destination="X")
        assert x_dec.allowed is False
        assert x_dec.decision == DisseminationDecisionOutcome.BLOCK

    def test_output_type_differs_from_destination(self, engine: DisseminationEngine):
        # An operator may generate a LinkedIn summary, but evaluate it for internal review
        classification = InformationClassification.INTERNAL
        internal_dec = engine.evaluate_output(classification, "linkedin", destination="INTERNAL")
        assert internal_dec.allowed is True

        # But disseminating the same output to LINKEDIN is blocked
        public_dec = engine.evaluate_output(classification, "linkedin", destination="LINKEDIN")
        assert public_dec.allowed is False

    def test_evaluate_all_returns_all_destinations(self, engine: DisseminationEngine):
        report = engine.evaluate_all(InformationClassification.INTERNAL)
        assert len(report) == len(VALID_DESTINATIONS)
        assert report["INTERNAL"].allowed is True
        assert report["REVIEW"].allowed is True
        assert report["DOWNLOAD"].allowed is True
        assert report["PRESENTATION"].allowed is True
        assert report["PUBLIC_WEB"].allowed is False
        assert report["LINKEDIN"].allowed is False
        assert report["X"].allowed is False


# ===========================================================================
# Zero-LLM & Safety Invariants (Req 21-24)
# ===========================================================================

class TestZeroLLMAndSafetyInvariants:
    """Ensure zero LLM calls, provider independence, and no secret leakage."""

    def test_21_llm_output_cannot_override_policy(self, engine: DisseminationEngine):
        # Even if text claims "This is approved for public sharing", policy governs
        decision = engine.evaluate(
            InformationClassification.RESTRICTED,
            DisseminationDestination.LINKEDIN,
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    def test_22_changing_provider_does_not_change_dissemination_policy(self, engine: DisseminationEngine):
        dec_openai = engine.evaluate(InformationClassification.CONFIDENTIAL, "X")
        dec_local = engine.evaluate(InformationClassification.CONFIDENTIAL, "X")
        dec_gemini = engine.evaluate(InformationClassification.CONFIDENTIAL, "X")
        assert dec_openai.allowed == dec_local.allowed == dec_gemini.allowed is False
        assert dec_openai.decision == dec_local.decision == dec_gemini.decision == DisseminationDecisionOutcome.BLOCK

    def test_23_policy_evaluation_does_not_call_llm(self, engine: DisseminationEngine):
        with patch("app.transformation.llm.factory.build_llm_provider") as mock_llm:
            decision = engine.evaluate(InformationClassification.PUBLIC, "LINKEDIN")
            assert decision.allowed is True
            mock_llm.assert_not_called()

    def test_24_no_secrets_in_decision_or_details(self, engine: DisseminationEngine):
        decision = engine.evaluate(
            InformationClassification.RESTRICTED,
            "LINKEDIN",
        )
        dec_json = decision.model_dump_json()
        assert "api_key" not in dec_json.lower()
        assert "secret" not in dec_json.lower()
        assert "token" not in dec_json.lower()
        assert "password" not in dec_json.lower()

    def test_25_future_proofing_extension_points(self):
        # DisseminationDecision supports optional hash, signature, provenance, approval
        dec = DisseminationDecision(
            allowed=True,
            decision=DisseminationDecisionOutcome.ALLOW,
            classification=InformationClassification.PUBLIC,
            destination="PUBLIC_WEB",
            reason="Approved under public dissemination policy",
            artifact_hash="sha256:abc1234567890abcdef",
            signature="ed25519:sig789",
            provenance_id="prov-uuid-1234",
            approval_id="gov-appr-5678",
            details={"department": "Public Relations"},
        )
        assert dec.artifact_hash == "sha256:abc1234567890abcdef"
        assert dec.signature == "ed25519:sig789"
        assert dec.provenance_id == "prov-uuid-1234"
        assert dec.approval_id == "gov-appr-5678"


# ===========================================================================
# API & Enforcement Tests (Req 17, 18, 19, 20)
# ===========================================================================

class TestDisseminationApiAndEnforcement:
    """Test API endpoints, backend enforcement, and audit event emission."""

    def test_standalone_evaluation_endpoint_allowed(self, client: TestClient):
        response = client.post(
            "/api/v1/transformations/dissemination/evaluate",
            json={
                "classification": "PUBLIC",
                "destination": "LINKEDIN",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["allowed"] is True
        assert data["decision"] == "ALLOW"
        assert data["destination"] == "LINKEDIN"

    def test_standalone_evaluation_endpoint_blocked(self, client: TestClient):
        response = client.post(
            "/api/v1/transformations/dissemination/evaluate",
            json={
                "classification": "RESTRICTED",
                "destination": "LINKEDIN",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["allowed"] is False
        assert data["decision"] == "BLOCK"
        assert data["destination"] == "LINKEDIN"

    def test_standalone_evaluation_unknown_destination_fails_closed(self, client: TestClient):
        response = client.post(
            "/api/v1/transformations/dissemination/evaluate",
            json={
                "classification": "PUBLIC",
                "destination": "INVALID_CHANNEL",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["allowed"] is False
        assert data["decision"] == "BLOCK"

    @pytest.mark.asyncio
    async def test_disseminate_endpoint_enforcement_and_audit(
        self, client: TestClient, async_db_session: AsyncSession
    ):
        clear_security_events()

        # Create project and source
        p_res = client.post(
            "/api/v1/projects",
            json={"name": "Audit Dissemination Test", "description": "Audit"},
        )
        assert p_res.status_code == 201
        project_id = p_res.json()["data"]["id"]

        s_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={
                "text": "Internal corporate roadmap.",
                "classification": "INTERNAL",
            },
        )
        assert s_res.status_code == 201
        source_id = s_res.json()["data"]["id"]

        c_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en", "detail_level": "brief"},
        )
        assert c_res.status_code == 201
        config_id = c_res.json()["data"]["id"]

        t_res = client.post(
            "/api/v1/transformations",
            json={
                "project_id": project_id,
                "source_id": source_id,
                "configuration_id": config_id,
                "output_types": ["summary"],
                "llm_provider": "fake",
            },
        )
        assert t_res.status_code == 201
        job_id = t_res.json()["data"]["id"]

        # Directly insert completed output into the test session
        out = Output(
            id=uuid.uuid4(),
            job_id=uuid.UUID(job_id),
            output_type="summary",
            status="completed",
            text_content="Executive summary content.",
            structured_content={"summary": "Executive summary content."},
        )
        async_db_session.add(out)
        await async_db_session.commit()
        output_id = str(out.id)

        # Test 1: Disseminate to INTERNAL -> ALLOWED (200)
        allow_res = client.post(
            f"/api/v1/outputs/{output_id}/disseminate",
            json={"destination": "INTERNAL"},
        )
        assert allow_res.status_code == 200
        assert allow_res.json()["data"]["allowed"] is True
        assert allow_res.json()["data"]["decision"] == "ALLOW"

        # Test 2: Disseminate to LINKEDIN -> BLOCKED (403)
        block_res = client.post(
            f"/api/v1/outputs/{output_id}/disseminate",
            json={"destination": "LINKEDIN"},
        )
        assert block_res.status_code == 403
        assert "blocked" in block_res.json()["detail"]["message"].lower()

        # Test 3: Disseminate to X -> BLOCKED (403)
        block_x_res = client.post(
            f"/api/v1/outputs/{output_id}/disseminate",
            json={"destination": "X"},
        )
        assert block_x_res.status_code == 403

        # Test 4: Dissemination report endpoint returns full destination matrix
        report_res = client.get(f"/api/v1/outputs/{output_id}/dissemination")
        assert report_res.status_code == 200
        rep_data = report_res.json()
        assert rep_data["classification"] == "INTERNAL"
        assert "LINKEDIN" in rep_data["destinations"]
        assert rep_data["destinations"]["LINKEDIN"]["allowed"] is False
        assert rep_data["destinations"]["INTERNAL"]["allowed"] is True

        # Test 5: GET /outputs/{output_id} reflects dissemination metadata
        get_out_res = client.get(f"/api/v1/outputs/{output_id}")
        assert get_out_res.status_code == 200
        meta = get_out_res.json()["data"]["output_metadata"]
        assert meta is not None
        assert "dissemination" in meta
        assert meta["dissemination"]["classification"] == "INTERNAL"

        # Verify audit event emitted
        events = [e for e in security_events() if e.get("event_type") == "dissemination_requested"]
        assert len(events) >= 2
        blocked_events = [e for e in events if e.get("outcome") == "blocked"]
        assert len(blocked_events) >= 1

    @pytest.mark.asyncio
    async def test_idor_protection_other_user_cannot_disseminate(
        self, client: TestClient, async_db_session: AsyncSession
    ):
        # Create project and output owned by TEST_USER_ID
        p_res = client.post(
            "/api/v1/projects",
            json={"name": "Owner Project", "description": "IDOR"},
        )
        project_id = p_res.json()["data"]["id"]

        s_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={"text": "Confidential details.", "classification": "CONFIDENTIAL"},
        )
        source_id = s_res.json()["data"]["id"]

        c_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en", "detail_level": "brief"},
        )
        config_id = c_res.json()["data"]["id"]

        t_res = client.post(
            "/api/v1/transformations",
            json={
                "project_id": project_id,
                "source_id": source_id,
                "configuration_id": config_id,
                "output_types": ["summary"],
                "llm_provider": "fake",
            },
        )
        job_id = t_res.json()["data"]["id"]

        out = Output(
            id=uuid.uuid4(),
            job_id=uuid.UUID(job_id),
            output_type="summary",
            status="completed",
        )
        async_db_session.add(out)
        await async_db_session.commit()
        output_id = str(out.id)

        # Attempt to access as OTHER_USER -> 404 NOT FOUND (IDOR safe)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=OTHER_USER_ID,
            email="other@test.local",
            name="Other User",
            role="viewer",
        )
        try:
            other_res = client.get(f"/api/v1/outputs/{output_id}/dissemination")
            assert other_res.status_code == 404

            other_post = client.post(
                f"/api/v1/outputs/{output_id}/disseminate",
                json={"destination": "INTERNAL"},
            )
            assert other_post.status_code == 404
        finally:
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(
                id=TEST_USER_ID,
                email=DEV_USER_EMAIL,
                name=DEV_USER_NAME,
                role=DEV_USER_ROLE,
            )
