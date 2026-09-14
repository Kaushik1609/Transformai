"""
TransformIQ / KaryaSetu AI — Phase 2C Routing & Provider Registry Tests

Covers:
1. PUBLIC -> cloud provider
2. PUBLIC -> private/local provider
3. INTERNAL -> compliant controlled/internal route
4. CONFIDENTIAL -> private/local only
5. RESTRICTED -> private/local only
6. CONFIDENTIAL -> requested OpenAI denied
7. RESTRICTED -> requested Gemini denied
8. unknown provider -> UNKNOWN_PROVIDER
9. fake provider in development/test allowed where existing policy permits
10. fake provider in production denied
11. missing cloud credentials -> COMPLIANT_PROVIDER_UNAVAILABLE
12. missing private/local configuration -> COMPLIANT_PROVIDER_UNAVAILABLE
13. confidential + local unavailable -> fail closed
14. restricted + local unavailable -> fail closed
15. sensitive request never falls back to cloud
16. public/internal compliant fallback
17. requested valid model
18. requested unsupported model
19. worker uses routed provider
20. sync worker uses same routing
21. routing failure causes zero LLM invocation
22. routing failure causes zero artifact generation
23. registry determinism
24. provider injection
25. Phase 2A/2B regression
26. Strict Security Test: CONFIDENTIAL/RESTRICTED with no compliant local provider
"""
import os
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
)
from app.policy.engine import PolicyEngine, get_policy_engine
from app.policy.registry import (
    ModelDescriptor,
    ProviderDescriptor,
    ProviderRegistry,
    get_provider_registry,
)
from app.policy.routing import (
    ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
    ERROR_POLICY_DENIED,
    ERROR_PRODUCTION_TEST_PROVIDER,
    ERROR_UNKNOWN_PROVIDER,
    ERROR_UNSUPPORTED_MODEL,
    PolicyRouter,
    get_policy_router,
)
from app.policy.schemas import (
    PolicyDecision,
    ProcessingRoute,
    ProviderCategory,
    RouteDecision,
)
from app.transformation.llm import FakeLLMProvider, LLMProvider
from app.transformation.llm.router_factory import (
    build_routed_llm_provider,
    instantiate_routed_provider,
)
from app.transformation.service import (
    execute_transformation_job_sync,
    run_transformation_job,
)


TEST_USER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


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
# 1. REGISTRY DETERMINISM & DESCRIPTORS
# ===========================================================================

class TestProviderRegistry:
    def test_23_registry_determinism(self):
        """Registry is deterministic, immutable, and side-effect free."""
        reg1 = get_provider_registry()
        reg2 = ProviderRegistry()

        assert reg1.list_providers() == reg2.list_providers()
        assert any(p.provider_id == "openai" for p in reg1.list_providers())
        assert any(p.provider_id == "gemini" for p in reg1.list_providers())
        assert any(p.provider_id == "local" for p in reg1.list_providers())
        assert any(p.provider_id == "fake" for p in reg1.list_providers())

        # Alias resolution is deterministic
        assert reg1.get_provider("ollama").provider_category == reg1.get_provider("local").provider_category
        assert reg1.get_provider("on_prem") == reg1.get_provider("local")

        desc = reg1.get_provider("openai")
        assert desc is not None
        assert desc.provider_category == ProviderCategory.EXTERNAL_CLOUD
        assert desc.processing_route == ProcessingRoute.CLOUD
        assert desc.requires_credential is True
        assert len(desc.supported_models) > 0

        # Deterministic lookup
        model = reg1.get_model("openai", "gpt-4o-mini")
        assert model is not None
        assert model.model_id == "gpt-4o-mini"
        assert model.context_window > 0

        # Unsupported model lookup returns None
        assert reg1.get_model("openai", "nonexistent-model-xyz") is None


# ===========================================================================
# 2. DETERMINISTIC ROUTING TESTS
# ===========================================================================

class TestPolicyRouter:
    def test_1_public_to_cloud_provider(self):
        """PUBLIC data can route to an external cloud provider (OpenAI or Gemini)."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.PUBLIC,
            requested_provider="openai",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.provider_id == "openai"
        assert decision.provider_category == ProviderCategory.EXTERNAL_CLOUD
        assert decision.processing_route == ProcessingRoute.CLOUD
        assert decision.error_code is None

    def test_2_public_to_private_local_provider(self):
        """PUBLIC data can route to a private/local provider (more secure route accepted)."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.PUBLIC,
            requested_provider="local",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.provider_id == "local"
        assert decision.provider_category == ProviderCategory.PRIVATE_LOCAL
        assert decision.processing_route == ProcessingRoute.PRIVATE_LOCAL
        assert decision.error_code is None

    def test_3_internal_to_compliant_controlled_internal_route(self):
        """INTERNAL data routes to compliant controlled/internal route."""
        router = get_policy_router()
        # In test/dev environment, fake provider provides CONTROLLED_INTERNAL route
        decision = router.resolve_route(
            classification=InformationClassification.INTERNAL,
            requested_provider="fake",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.provider_id == "fake"
        assert decision.processing_route == ProcessingRoute.CONTROLLED_INTERNAL

    def test_4_confidential_to_private_local_only(self):
        """CONFIDENTIAL data resolves successfully to private/local route."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.CONFIDENTIAL,
            requested_provider="local",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.provider_id == "local"
        assert decision.processing_route == ProcessingRoute.PRIVATE_LOCAL

    def test_5_restricted_to_private_local_only(self):
        """RESTRICTED data resolves successfully to private/local route."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.RESTRICTED,
            requested_provider="local",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.provider_id == "local"
        assert decision.processing_route == ProcessingRoute.PRIVATE_LOCAL

    def test_6_confidential_requested_openai_denied(self):
        """CONFIDENTIAL + requested OpenAI cloud is denied deterministically."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.CONFIDENTIAL,
            requested_provider="openai",
            environment="test",
        )
        assert decision.allowed is False
        assert decision.provider_id == "openai"
        assert decision.error_code == ERROR_POLICY_DENIED
        assert "Confidential information requires private or local model processing" in decision.reason

    def test_7_restricted_requested_gemini_denied(self):
        """RESTRICTED + requested Gemini cloud is denied deterministically."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.RESTRICTED,
            requested_provider="gemini",
            environment="test",
        )
        assert decision.allowed is False
        assert decision.provider_id == "gemini"
        assert decision.error_code == ERROR_POLICY_DENIED
        assert "Restricted information cannot be processed by external cloud" in decision.reason

    def test_8_unknown_provider_fails_closed(self):
        """Unknown provider is rejected with UNKNOWN_PROVIDER error code."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.PUBLIC,
            requested_provider="unregistered_provider_xyz",
            environment="test",
        )
        assert decision.allowed is False
        assert decision.error_code == ERROR_UNKNOWN_PROVIDER
        assert "Unknown or unsupported" in decision.reason

    def test_9_fake_provider_allowed_in_dev_test(self):
        """Fake provider is allowed in development/test environments."""
        router = get_policy_router()
        for env in ("test", "development"):
            decision = router.resolve_route(
                classification=InformationClassification.INTERNAL,
                requested_provider="fake",
                environment=env,
            )
            assert decision.allowed is True
            assert decision.provider_id == "fake"

    def test_10_fake_provider_denied_in_production(self):
        """Fake provider is blocked in production environment deterministically."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.INTERNAL,
            requested_provider="fake",
            environment="production",
        )
        assert decision.allowed is False
        assert decision.error_code == ERROR_PRODUCTION_TEST_PROVIDER
        assert "not permitted in production" in decision.reason

    def test_17_requested_valid_model(self):
        """Valid requested model is resolved successfully."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.PUBLIC,
            requested_provider="openai",
            requested_model="gpt-4o-mini",
            environment="test",
        )
        assert decision.allowed is True
        assert decision.model_id == "gpt-4o-mini"

    def test_18_requested_unsupported_model(self):
        """Unsupported model for a provider is rejected with UNSUPPORTED_MODEL."""
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.PUBLIC,
            requested_provider="openai",
            requested_model="unsupported-model-999",
            environment="test",
        )
        assert decision.allowed is False
        assert decision.error_code == ERROR_UNSUPPORTED_MODEL
        assert "not supported" in decision.reason


# ===========================================================================
# 3. ROUTER FACTORY & PROVIDER INJECTION TESTS
# ===========================================================================

class TestRouterFactory:
    def test_24_provider_injection_fake(self):
        """Factory instantiates FakeLLMProvider for test/development."""
        decision = RouteDecision(
            allowed=True,
            provider_id="fake",
            model_id="fake-default",
            provider_category=ProviderCategory.TEST_DEVELOPMENT,
            processing_route=ProcessingRoute.CONTROLLED_INTERNAL,
            classification=InformationClassification.INTERNAL,
            reason="Approved",
        )
        provider = instantiate_routed_provider(decision)
        assert isinstance(provider, FakeLLMProvider)
        assert isinstance(provider, LLMProvider)

    def test_11_missing_cloud_credentials(self, monkeypatch):
        """Missing cloud credentials raises COMPLIANT_PROVIDER_UNAVAILABLE."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)

        decision = RouteDecision(
            allowed=True,
            provider_id="openai",
            model_id="gpt-4o-mini",
            provider_category=ProviderCategory.EXTERNAL_CLOUD,
            processing_route=ProcessingRoute.CLOUD,
            classification=InformationClassification.PUBLIC,
            reason="Approved",
        )
        with pytest.raises(Exception) as exc_info:
            instantiate_routed_provider(decision)
        assert ERROR_COMPLIANT_PROVIDER_UNAVAILABLE in str(exc_info.value)

    def test_12_missing_private_local_configuration(self, monkeypatch):
        """Missing private local configuration raises COMPLIANT_PROVIDER_UNAVAILABLE."""
        monkeypatch.setattr(settings, "LLM_BASE_URL", "", raising=False)

        decision = RouteDecision(
            allowed=True,
            provider_id="local",
            model_id="llama3.1:8b",
            provider_category=ProviderCategory.PRIVATE_LOCAL,
            processing_route=ProcessingRoute.PRIVATE_LOCAL,
            classification=InformationClassification.CONFIDENTIAL,
            reason="Approved",
        )
        with pytest.raises(Exception) as exc_info:
            instantiate_routed_provider(decision)
        assert ERROR_COMPLIANT_PROVIDER_UNAVAILABLE in str(exc_info.value)

    def test_15_sensitive_request_never_falls_back_to_cloud(self, monkeypatch):
        """CONFIDENTIAL / RESTRICTED routed provider wraps with ProviderManager having NO cloud fallbacks."""
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "openai")  # Global fallback configured as cloud

        decision = RouteDecision(
            allowed=True,
            provider_id="local",
            model_id="llama3.1:8b",
            provider_category=ProviderCategory.PRIVATE_LOCAL,
            processing_route=ProcessingRoute.PRIVATE_LOCAL,
            classification=InformationClassification.CONFIDENTIAL,
            reason="Approved",
        )

        manager = build_routed_llm_provider(decision, environment="test")
        # Secondary fallback must NEVER be set for sensitive data
        assert manager.fallback is None

    def test_16_public_internal_compliant_fallback(self, monkeypatch):
        """PUBLIC allows compliant fallback provider (e.g., fake in test environment)."""
        monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "fake")

        decision = RouteDecision(
            allowed=True,
            provider_id="fake",
            model_id="fake-default",
            provider_category=ProviderCategory.TEST_DEVELOPMENT,
            processing_route=ProcessingRoute.CONTROLLED_INTERNAL,
            classification=InformationClassification.PUBLIC,
            reason="Approved",
        )
        manager = build_routed_llm_provider(decision, environment="test")
        assert manager.primary is not None
        assert isinstance(manager.primary, FakeLLMProvider)


# ===========================================================================
# 4. WORKER & SYNC ROUTING INTEGRATION
# ===========================================================================

class TestWorkerRoutingIntegration:
    def test_19_worker_uses_routed_provider(self, sync_db_session: Session):
        """Async worker resolves provider via PolicyRouter and executes successfully."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Worker Route Proj")
        sync_db_session.add(proj)
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Public documentation text.",
            source_metadata={"classification": "PUBLIC"},
        )
        sync_db_session.add(src)

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "fake"},
        )
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute.return_value = {"outputs": []}

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id)
            assert result.get("policy_denied") is not True
            mock_orchestrator.execute.assert_called_once()

    def test_20_sync_worker_uses_same_routing(self, sync_db_session: Session, sqlite_engine):
        """Sync worker executes with the same deterministic routing logic."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Sync Worker Proj")
        sync_db_session.add(proj)
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Internal company policy text.",
            source_metadata={"classification": "INTERNAL"},
        )
        sync_db_session.add(src)

        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "fake"},
        )
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute.return_value = {"outputs": []}

        with patch("app.content_intelligence.service.ContentIntelligenceService.analyze_source"), \
             patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = execute_transformation_job_sync(str(job.id), engine=sqlite_engine)
            assert result.get("policy_denied") is not True
            mock_orchestrator.execute.assert_called_once()

    def test_21_22_routing_failure_zero_llm_zero_artifacts(self, sync_db_session: Session):
        """Routing failure causes zero LLM invocation and zero artifact generation."""
        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Fail Routing Proj")
        sync_db_session.add(proj)
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Confidential business strategy.",
            source_metadata={"classification": "CONFIDENTIAL"},
        )
        sync_db_session.add(src)

        # Requests cloud provider (OpenAI) for CONFIDENTIAL data
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "openai"},
        )
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_llm = MagicMock()
        mock_orchestrator = MagicMock()

        with patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):
            result = run_transformation_job(sync_db_session, job.id, llm_provider=mock_llm)
            assert result["policy_denied"] is True
            assert result["skipped"] is True
            assert "Confidential information requires private or local model processing" in result["reason"]

            # Zero LLM invocation
            mock_llm.generate.assert_not_called()
            mock_orchestrator.execute.assert_not_called()

            # Zero artifacts generated & job status is failed
            sync_db_session.refresh(job)
            assert job.status == "failed"
            assert "Processing blocked by policy" in job.error_message


# ===========================================================================
# 5. STRICT SECURITY TEST: CONFIDENTIAL/RESTRICTED WITH LOCAL UNAVAILABLE
# ===========================================================================

class TestSecurityFailClosed:
    @pytest.mark.parametrize("classification", [InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED])
    def test_13_14_26_strict_security_confidential_restricted_local_unavailable_fails_closed(
        self, classification: InformationClassification, sync_db_session: Session, monkeypatch
    ):
        """
        IMPORTANT SECURITY TEST:
        For CONFIDENTIAL / RESTRICTED when no compliant local provider is configured:
        Assert:
        - no OpenAI/Gemini provider instantiated
        - no LLM call
        - no orchestrator execution
        - no artifact generated
        - job fails with explicit routing error
        """
        # Ensure no local LLM configuration is set
        monkeypatch.setattr(settings, "LLM_BASE_URL", "", raising=False)
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "openai", raising=False)  # Dangerous fallback should NEVER be used

        proj = Project(id=uuid.uuid4(), user_id=TEST_USER_ID, name="Strict Security Proj")
        sync_db_session.add(proj)
        src = Source(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_type="text",
            extracted_text="Top secret internal document.",
            source_metadata={"classification": classification.value},
        )
        sync_db_session.add(src)

        # Job requests local provider
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=proj.id,
            source_id=src.id,
            configuration_id=uuid.uuid4(),
            status="queued",
            requested_outputs={"output_types": ["summary"], "llm_provider": "local"},
        )
        sync_db_session.add(job)
        sync_db_session.commit()

        mock_orchestrator = MagicMock()

        with patch("app.transformation.llm.router_factory.OpenAILLMProvider") as mock_openai, \
             patch("app.transformation.llm.router_factory.GeminiLLMProvider") as mock_gemini, \
             patch("app.transformation.service.TransformationOrchestrator", return_value=mock_orchestrator):

            result = run_transformation_job(sync_db_session, job.id)

            # 1. Job fails with explicit routing error
            assert result["routing_failed"] is True
            assert result["error_code"] == ERROR_COMPLIANT_PROVIDER_UNAVAILABLE

            # 2. No OpenAI or Gemini provider instantiated
            mock_openai.assert_not_called()
            mock_gemini.assert_not_called()

            # 3. No orchestrator execution
            mock_orchestrator.execute.assert_not_called()

            # 4. Job status failed in DB
            sync_db_session.refresh(job)
            assert job.status == "failed"
            assert "Processing blocked by routing policy" in job.error_message


# ===========================================================================
# 6. API PRE-ROUTING GATE TESTS
# ===========================================================================

class TestApiRoutingGate:
    def test_api_rejects_confidential_with_cloud_provider(self, client: TestClient):
        """API rejects CONFIDENTIAL source with external cloud provider with HTTP 403 before job creation."""
        # 1. Create project
        proj_res = client.post("/api/v1/projects", json={"name": "Confidential Routing API Proj"})
        assert proj_res.status_code == 201
        project_id = proj_res.json()["data"]["id"]

        # 2. Add CONFIDENTIAL source
        source_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={
                "text": "Restricted architecture.",
                "classification": "CONFIDENTIAL",
            },
        )
        assert source_res.status_code == 201
        source_id = source_res.json()["data"]["id"]

        # 3. Create configuration
        cfg_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en"},
        )
        assert cfg_res.status_code == 201
        config_id = cfg_res.json()["data"]["id"]

        # 4. Request transformation with external cloud provider (openai)
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
        assert transform_res.status_code == 403
        data = transform_res.json()
        assert "Confidential information requires private or local model processing" in data["detail"]["reason"]
        assert data["detail"]["classification"] == "CONFIDENTIAL"

    def test_api_rejects_unknown_provider(self, client: TestClient):
        """API rejects unknown LLM provider with HTTP 403 before job creation."""
        proj_res = client.post("/api/v1/projects", json={"name": "Unknown Provider Proj"})
        project_id = proj_res.json()["data"]["id"]

        source_res = client.post(
            f"/api/v1/projects/{project_id}/sources/text",
            json={
                "text": "Public information.",
                "classification": "PUBLIC",
            },
        )
        source_id = source_res.json()["data"]["id"]

        cfg_res = client.post(
            f"/api/v1/projects/{project_id}/configurations",
            json={"language": "en"},
        )
        config_id = cfg_res.json()["data"]["id"]

        transform_res = client.post(
            "/api/v1/transformations",
            json={
                "project_id": project_id,
                "source_id": source_id,
                "configuration_id": config_id,
                "output_types": ["summary"],
                "llm_provider": "unknown_ai_vendor_xyz",
            },
        )
        assert transform_res.status_code == 403
        data = transform_res.json()
        assert "Unknown or unsupported" in data["detail"]["reason"]


# ===========================================================================
# 7. PHASE 2A/2B REGRESSION
# ===========================================================================

class TestPhase2a2bRegression:
    def test_25_phase2a_2b_policy_engine_guarantees(self):
        """Phase 2A/2B PolicyEngine guarantees remain intact and authoritative."""
        from app.policy.schemas import PolicyEvaluationContext
        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.RESTRICTED,
            requested_provider="openai",
            environment="test",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Restricted information cannot be processed by external cloud" in decision.reason

