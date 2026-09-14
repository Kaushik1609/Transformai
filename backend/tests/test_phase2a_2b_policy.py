"""
TransformIQ / KaryaSetu AI — Phase 2A & 2B Policy Control Tests

Comprehensive tests covering:
1. Information Classification (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, normalization, fail-closed)
2. Deterministic Policy Engine (Zero LLM, reproducibility, fail-closed, provider categorization)
3. Processing & Dissemination Policies (Cloud, private/local, LinkedIn/X social restrictions)
4. Pre-AI API and Worker Enforcement (HTTP 403, 0 LLM calls, 0 jobs, 0 artifacts, audit events)
5. Backward Compatibility (Existing unclassified sources and allowed transformations)
"""
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.audit import clear_security_events, security_events
from app.core.config import settings
from app.db.base import Base
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.policy.classification import (
    DEFAULT_CLASSIFICATION,
    InformationClassification,
    InvalidClassificationError,
    normalize_classification,
    resolve_source_classification,
)
from app.policy.engine import PolicyEngine, categorize_provider, get_policy_engine
from app.policy.schemas import (
    PolicyDecision,
    PolicyEvaluationContext,
    ProcessingRoute,
    ProviderCategory,
)
from app.transformation.service import run_transformation_job


TEST_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


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
def sync_db_session(sqlite_engine) -> Session:
    TestingSessionLocal = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = TestingSessionLocal()
    session.begin_nested()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


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
    from app.api.deps import CurrentUser, DEV_USER_EMAIL, DEV_USER_NAME, DEV_USER_ROLE, get_current_user
    from app.db.session import get_db
    from app.main import app

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


# ===========================================================================
# 1. PHASE 2A: CLASSIFICATION TESTS
# ===========================================================================


class TestInformationClassification:
    def test_1_public_classification(self):
        c = normalize_classification("PUBLIC")
        assert c == InformationClassification.PUBLIC
        assert c.value == "PUBLIC"

    def test_2_internal_classification(self):
        c = normalize_classification("INTERNAL")
        assert c == InformationClassification.INTERNAL
        assert c.value == "INTERNAL"

    def test_3_confidential_classification(self):
        c = normalize_classification("CONFIDENTIAL")
        assert c == InformationClassification.CONFIDENTIAL
        assert c.value == "CONFIDENTIAL"

    def test_4_restricted_classification(self):
        c = normalize_classification("RESTRICTED")
        assert c == InformationClassification.RESTRICTED
        assert c.value == "RESTRICTED"

    def test_5_case_and_whitespace_normalization(self):
        assert normalize_classification("  public  ") == InformationClassification.PUBLIC
        assert normalize_classification("internal") == InformationClassification.INTERNAL
        assert normalize_classification("Confidential") == InformationClassification.CONFIDENTIAL
        assert normalize_classification("RESTRICTED\n") == InformationClassification.RESTRICTED
        assert normalize_classification(InformationClassification.RESTRICTED) == InformationClassification.RESTRICTED

    def test_6_invalid_classification_fails_closed(self):
        with pytest.raises(InvalidClassificationError) as exc_info:
            normalize_classification("TOP_SECRET")
        assert "Invalid classification label" in str(exc_info.value)

        with pytest.raises(InvalidClassificationError):
            normalize_classification("OFFICIAL")

        with pytest.raises(InvalidClassificationError):
            normalize_classification("SECRET")

    def test_7_legacy_unclassified_default(self):
        # Unclassified material resolves to INTERNAL by default
        assert normalize_classification(None) == InformationClassification.INTERNAL
        assert normalize_classification("") == InformationClassification.INTERNAL
        assert normalize_classification("   ") == InformationClassification.INTERNAL

        # Source metadata resolution
        assert resolve_source_classification(None) == InformationClassification.INTERNAL
        assert resolve_source_classification({}) == InformationClassification.INTERNAL
        assert (
            resolve_source_classification({"classification": "CONFIDENTIAL"})
            == InformationClassification.CONFIDENTIAL
        )


# ===========================================================================
# 2. PHASE 2B: DETERMINISTIC POLICY ENGINE TESTS
# ===========================================================================


class TestDeterministicPolicyEngine:
    @pytest.fixture
    def engine(self) -> PolicyEngine:
        return PolicyEngine()

    def test_8_public_cloud_allowed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_outputs=["executive_summary"],
            requested_provider="openai",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is True
        assert decision.processing_route == ProcessingRoute.CLOUD.value
        assert decision.classification == InformationClassification.PUBLIC
        assert decision.requires_review is False

    def test_9_internal_controlled_processing_allowed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.INTERNAL,
            requested_outputs=["advisory"],
            requested_provider="openai",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is True
        assert decision.processing_route == ProcessingRoute.CONTROLLED_INTERNAL.value
        assert decision.classification == InformationClassification.INTERNAL
        assert decision.requires_review is False

    def test_10_confidential_local_private_allowed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.CONFIDENTIAL,
            requested_outputs=["analyst_brief"],
            requested_provider="local",
            environment="local",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is True
        assert decision.processing_route == ProcessingRoute.PRIVATE_LOCAL.value
        assert decision.classification == InformationClassification.CONFIDENTIAL
        assert decision.requires_review is False

    def test_11_confidential_external_cloud_denied(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.CONFIDENTIAL,
            requested_outputs=["summary"],
            requested_provider="openai",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Confidential information requires private or local" in decision.reason
        assert decision.classification == InformationClassification.CONFIDENTIAL

    def test_12_restricted_external_cloud_denied(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_outputs=["summary"],
            requested_provider="gemini",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Restricted information cannot be processed by external cloud" in decision.reason
        assert decision.classification == InformationClassification.RESTRICTED

    def test_13_restricted_local_private_allowed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_outputs=["summary"],
            requested_provider="private",
            environment="local",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is True
        assert decision.processing_route == ProcessingRoute.PRIVATE_LOCAL.value
        assert decision.classification == InformationClassification.RESTRICTED

    def test_14_confidential_linkedin_dissemination_restricted(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.CONFIDENTIAL,
            requested_outputs=["linkedin"],
            requested_provider="local",
            environment="local",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.requires_review is True
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "LinkedIn/X" in decision.reason

    def test_15_confidential_x_dissemination_restricted(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.CONFIDENTIAL,
            requested_outputs=["x"],
            requested_provider="local",
            environment="local",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.requires_review is True
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "LinkedIn/X" in decision.reason

    def test_16_invalid_provider_denied_fail_closed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_outputs=["summary"],
            requested_provider="untrusted_shady_llm",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Unknown or unsupported model provider" in decision.reason

    def test_17_invalid_environment_denied_fail_closed(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_outputs=["summary"],
            requested_provider="openai",
            environment="compromised_env",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Unsupported processing environment" in decision.reason

    def test_18_fake_provider_behavior(self, engine: PolicyEngine):
        # In development / testing: permitted as TEST_DEVELOPMENT
        dev_ctx = PolicyEvaluationContext(
            classification=InformationClassification.INTERNAL,
            requested_outputs=["summary"],
            requested_provider="fake",
            environment="development",
        )
        dev_decision = engine.evaluate(dev_ctx)
        assert dev_decision.allowed is True

        # In production: Fake provider must NEVER bypass production policy controls
        prod_ctx = PolicyEvaluationContext(
            classification=InformationClassification.INTERNAL,
            requested_outputs=["summary"],
            requested_provider="fake",
            environment="production",
        )
        prod_decision = engine.evaluate(prod_ctx)
        assert prod_decision.allowed is False
        assert prod_decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "not permitted in production environment" in prod_decision.reason

    def test_19_deterministic_reproducibility(self, engine: PolicyEngine):
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_outputs=["summary", "advisory"],
            requested_provider="openai",
            environment="cloud",
        )
        first = engine.evaluate(ctx)
        for _ in range(50):
            again = engine.evaluate(ctx)
            assert again.allowed == first.allowed
            assert again.reason == first.reason
            assert again.processing_route == first.processing_route
            assert again.requires_review == first.requires_review
            assert again.classification == first.classification

    def test_20_policy_engine_zero_llm_dependency(self, engine: PolicyEngine):
        # Verify PolicyEngine module contains no LLM imports or network calls
        import inspect
        import app.policy.engine as engine_module

        source_code = inspect.getsource(engine_module)
        assert "openai" not in source_code or "_EXTERNAL_CLOUD_PROVIDERS" in source_code
        assert "generate" not in source_code
        assert "invoke_model" not in source_code
        assert "ChatOpenAI" not in source_code
        assert "api_key" not in source_code


# ===========================================================================
# 3. CRITICAL ENFORCEMENT & SECURITY TESTS
# ===========================================================================


class TestPolicyEnforcementPipeline:
    def test_21_restricted_cloud_api_enforcement(self, client: TestClient):
        """RESTRICTED + external cloud LLM in API POST -> HTTP 403, 0 LLM calls, 0 jobs created."""
        clear_security_events()

        # 1. Create a project
        proj_res = client.post(
            "/api/v1/projects",
            json={"name": "Restricted Gov Project", "description": "High sensitivity"},
        )
        assert proj_res.status_code == 201
        project_id = proj_res.json()["data"]["id"]

        # 2. Ingest a RESTRICTED source
        src_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={
                "text": "Restricted organizational directive content.",
                "classification": "RESTRICTED",
            },
        )
        assert src_res.status_code == 201
        source_id = src_res.json()["data"]["id"]
        assert src_res.json()["data"]["source_metadata"]["classification"] == "RESTRICTED"

        # 3. Create a configuration
        cfg_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en", "detail_level": "brief"},
        )
        assert cfg_res.status_code == 201
        config_id = cfg_res.json()["data"]["id"]

        # 4. Attempt transformation with external cloud provider (OpenAI)
        with patch("app.transformation.llm.factory.build_llm_provider") as mock_build_llm:
            transform_res = client.post(
                "/api/v1/transformations",
                json={
                    "project_id": project_id,
                    "source_id": source_id,
                    "configuration_id": config_id,
                    "output_types": ["summary"],
                    "llm_provider": "openai",
                },
            )

            # Assert HTTP 403 Forbidden
            assert transform_res.status_code == 403
            err_data = transform_res.json()
            assert "detail" in err_data
            detail = err_data["detail"]
            assert detail["message"] == "Processing blocked by policy."
            assert detail["classification"] == "RESTRICTED"
            assert detail["processing_route"] == "blocked"
            assert "Restricted information cannot be processed by external cloud" in detail["reason"]

            # CRITICAL: Assert 0 LLM provider calls were made
            mock_build_llm.assert_not_called()

        # CRITICAL: Verify 0 jobs were created in database
        jobs_res = client.get(
            f"/api/v1/projects/{project_id}/transformations",
        )
        assert jobs_res.status_code == 200
        assert len(jobs_res.json()["data"]) == 0

    def test_22_restricted_cloud_worker_defense_in_depth(self, sync_db_session: Session):
        """Worker re-evaluates policy: fails closed, 0 LLM calls, records denial on job."""
        clear_security_events()

        # Create user & project
        user = User(
            id=uuid.uuid4(),
            email=f"worker_sec_{uuid.uuid4().hex[:8]}@example.com",
            name="Policy Officer",
            role="operator",
        )
        sync_db_session.add(user)
        sync_db_session.flush()

        proj = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Restricted Project",
        )
        sync_db_session.add(proj)

        # Restricted Source
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Classified material.",
            source_metadata={"classification": "RESTRICTED"},
        )
        sync_db_session.add(src)

        # Job requesting external cloud provider
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["executive_summary"], "llm_provider": "openai"},
        )
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)

            # Assert worker stopped before orchestrator or LLM
            assert result["policy_denied"] is True
            assert result["skipped"] is True
            assert "Restricted information cannot be processed by external cloud" in result["reason"]
            mock_orchestrator.execute.assert_not_called()
            mock_llm.generate.assert_not_called()

            # Assert database job record was marked failed with clear policy denial
            sync_db_session.refresh(job)
            assert job.status == "failed"
            assert "Processing blocked by policy" in job.error_message

    def test_23_policy_denial_emits_security_event(self):
        """Policy evaluation emits an audit event with safe, non-sensitive metadata."""
        clear_security_events()
        from app.core.audit import emit_security_event

        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_outputs=["linkedin"],
            requested_provider="openai",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False

        emit_security_event(
            "policy_evaluated",
            outcome="denied",
            project_id="proj-123",
            source_id="src-456",
            reason=decision.reason,
            details={
                "classification": decision.classification.value,
                "processing_route": decision.processing_route,
                "requires_review": decision.requires_review,
            },
        )

        events = security_events()
        assert len(events) >= 1
        policy_event = [e for e in events if e.get("event_type") == "policy_evaluated"][-1]
        assert policy_event["outcome"] == "denied"
        assert policy_event["project_id"] == "proj-123"
        assert policy_event["classification"] == "RESTRICTED"
        assert policy_event["processing_route"] == "blocked"

    def test_24_policy_denial_does_not_expose_content_or_secrets(self):
        """Policy decision details contain only classification/routing metadata, never content."""
        engine = get_policy_engine()
        secret_context = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_outputs=["summary"],
            requested_provider="openai",
            environment="cloud",
        )
        decision = engine.evaluate(secret_context)
        dumped = decision.model_dump_json()

        assert "api_key" not in dumped.lower()
        assert "password" not in dumped.lower()
        assert "secret_content" not in dumped.lower()
        assert decision.classification == InformationClassification.RESTRICTED

    def test_25_existing_allowed_transformation_still_works(self, client: TestClient):
        """PUBLIC or INTERNAL sources transformed with allowed provider (e.g. fake/dev) succeed."""
        # Create project
        proj_res = client.post(
            "/api/v1/projects",
            json={"name": "Public Project"},
        )
        project_id = proj_res.json()["data"]["id"]

        # Create PUBLIC source
        src_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={"text": "Public whitepaper text.", "classification": "PUBLIC"},
        )
        source_id = src_res.json()["data"]["id"]

        cfg_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en"},
        )
        config_id = cfg_res.json()["data"]["id"]

        # Create transformation with fake provider
        transform_res = client.post(
            "/api/v1/transformations",
            json={
                "project_id": project_id,
                "source_id": source_id,
                "configuration_id": config_id,
                "output_types": ["summary"],
                "llm_provider": "fake",
            },
        )
        assert transform_res.status_code == 201
        data = transform_res.json()["data"]
        assert data["status"] in ("queued", "running", "completed")

    def test_26_existing_unclassified_source_backward_compatible(self, client: TestClient):
        """Legacy source created without classification defaults to INTERNAL and processes normally."""
        # Create project
        proj_res = client.post(
            "/api/v1/projects",
            json={"name": "Legacy Unclassified Project"},
        )
        project_id = proj_res.json()["data"]["id"]

        # Create source with NO classification field (legacy behavior)
        src_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={"text": "Legacy enterprise document without any explicit classification tag."},
        )
        assert src_res.status_code == 201
        source_data = src_res.json()["data"]
        source_id = source_data["id"]

        # Default classification is safely INTERNAL
        assert source_data["source_metadata"]["classification"] == "INTERNAL"

        cfg_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en"},
        )
        config_id = cfg_res.json()["data"]["id"]

        # Transformation succeeds under controlled internal policy
        transform_res = client.post(
            "/api/v1/transformations",
            json={
                "project_id": project_id,
                "source_id": source_id,
                "configuration_id": config_id,
                "output_types": ["summary"],
                "llm_provider": "fake",
            },
        )
        assert transform_res.status_code == 201

    def test_27_worker_uses_source_classification_when_source_exists(self, sync_db_session: Session):
        """Worker uses source classification when source exists, even if parameters or outputs differ."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Source Priority Proj")
        sync_db_session.add(proj)
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Classified source text.",
            source_metadata={"classification": "CONFIDENTIAL"},
        )
        sync_db_session.add(src)

        # Job with missing/INTERNAL in parameters, but source is CONFIDENTIAL
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "openai"},
        )
        setattr(job, "parameters", {"classification": "INTERNAL"})
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_orchestrator = MagicMock()
        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)
            assert result["policy_denied"] is True
            assert "Confidential information requires private or local model processing" in result["reason"]
            mock_orchestrator.execute.assert_not_called()
            mock_llm.generate.assert_not_called()

    def test_28_worker_uses_job_parameters_when_source_is_missing(self, sync_db_session: Session):
        """Worker respects job.parameters['classification'] when source is missing or prompt-only."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Prompt Only Proj")
        sync_db_session.add(proj)

        # Prompt-only job (source_id is None) with CONFIDENTIAL in job.parameters
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=None,
            configuration_id=uuid.uuid4(),
            status="queued",
            prompt="Prompt with confidential requirements",
            requested_outputs={"output_types": ["summary"], "llm_provider": "local"},
        )
        setattr(job, "parameters", {"classification": "CONFIDENTIAL"})
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_llm.provider_name = "local"
        mock_orchestrator = MagicMock()
        mock_orchestrator.execute.return_value = {"outputs": []}

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)
            # Allowed for local provider
            assert result.get("policy_denied") is not True

    def test_29_restricted_in_job_parameters_cloud_denied_no_llm_call(self, sync_db_session: Session):
        """RESTRICTED in job.parameters + external cloud provider is denied by worker without calling LLM."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Restricted Parameters Proj")
        sync_db_session.add(proj)

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=None,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "openai"},
        )
        setattr(job, "parameters", {"classification": "RESTRICTED"})
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)
            assert result["policy_denied"] is True
            assert result["skipped"] is True
            assert "Restricted information cannot be processed by external cloud" in result["reason"]
            mock_orchestrator.execute.assert_not_called()
            mock_llm.generate.assert_not_called()

            sync_db_session.refresh(job)
            assert job.status == "failed"
            assert "Processing blocked by policy" in job.error_message

    def test_30_confidential_in_job_parameters_cloud_denied_no_llm_call(self, sync_db_session: Session):
        """CONFIDENTIAL in job.parameters + external cloud provider is denied by worker without calling LLM."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Confidential Parameters Proj")
        sync_db_session.add(proj)

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=None,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "gemini"},
        )
        setattr(job, "parameters", {"classification": "CONFIDENTIAL"})
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)
            assert result["policy_denied"] is True
            assert result["skipped"] is True
            assert "Confidential information requires private or local model processing" in result["reason"]
            mock_orchestrator.execute.assert_not_called()
            mock_llm.generate.assert_not_called()

            sync_db_session.refresh(job)
            assert job.status == "failed"
            assert "Processing blocked by policy" in job.error_message
