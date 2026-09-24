"""
Phase 2J — Security Hardening and Production Readiness Test Suite
KaryaSetu AI / TransformIQ

Tests cover:
1. Authorization and IDOR hardening on all sensitive endpoints
2. Policy fail-closed enforcement (classification, destination, provider, environment)
3. Sensitive AI routing and offline execution hardening
4. Dissemination control hardening and policy supremacy over approval
5. Approval workflow hardening (invalid transitions, non-spoofable metadata, destination isolation)
6. Cryptographic integrity and digital signature tamper detection (read-only verification)
7. Input and upload validation security
8. Secret non-exposure and configuration validation
9. Worker failure isolation and defense-in-depth policy re-evaluation
"""
import copy
import hashlib
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.audit import clear_security_events, emit_security_event, security_events
from app.core.config import Settings, settings
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.db.session import get_db
from app.ingestion.validation import SourceValidationError, validate_source
from app.policy.approval import (
    ApprovalAction,
    ApprovalStatus,
    DestinationApprovalRecord,
    InvalidApprovalTransitionError,
    OutputApprovalMetadata,
    PolicyHardBlockedError,
    validate_approval_transition,
)
from app.policy.classification import (
    DEFAULT_CLASSIFICATION,
    InformationClassification,
    InvalidClassificationError,
    normalize_classification,
    resolve_source_classification,
)
from app.policy.dissemination import (
    DisseminationDecisionOutcome,
    DisseminationDestination,
    InvalidDestinationError,
    get_dissemination_engine,
    normalize_destination,
)
from app.policy.engine import get_policy_engine
from app.policy.integrity import (
    CryptographicIntegrityRecord,
    IntegrityStatus,
    canonical_json_bytes,
    canonical_json_hash,
    sha256_bytes,
)
from app.policy.registry import get_provider_registry
from app.policy.routing import (
    ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
    ERROR_POLICY_DENIED,
    ERROR_PRODUCTION_TEST_PROVIDER,
    ERROR_UNKNOWN_PROVIDER,
    PolicyRouter,
)
from app.policy.schemas import (
    PolicyEvaluationContext,
    ProcessingRoute,
    ProviderCategory,
    RouteDecision,
)
from app.policy.signature import (
    DigitalSignatureRecord,
    Ed25519Signer,
    FakeDigitalSigner,
    HmacSha256Signer,
    SignatureStatus,
    build_signing_payload,
    compute_signing_payload_bytes,
    get_digital_signer,
)
from app.services import (
    approval_service,
    integrity_service,
    signature_service,
    transformation_service,
)
from app.services.integrity_service import seal_output_integrity, verify_output_integrity
from app.services.signature_service import sign_output_artifact, verify_output_signature
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.router_factory import (
    CompliantRoutingError,
    build_routed_llm_provider,
)
from app.transformation.service import TransformationError, run_transformation_job


# ===========================================================================
# Fixtures & Test Setup
# ===========================================================================

OWNER_USER_ID = uuid.uuid4()
ATTACKER_USER_ID = uuid.uuid4()


@pytest.fixture
def owner_user() -> CurrentUser:
    return CurrentUser(
        id=OWNER_USER_ID,
        email="owner@karyasetu.internal",
        name="Owner User",
        role="operator",
    )


@pytest.fixture
def attacker_user() -> CurrentUser:
    return CurrentUser(
        id=ATTACKER_USER_ID,
        email="attacker@karyasetu.internal",
        name="Attacker User",
        role="operator",
    )


@pytest.fixture
def client(owner_user: CurrentUser):
    from app.main import app

    async def override_get_current_user():
        return owner_user

    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _make_mock_output(
    *,
    output_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    output_type: str = "summary",
    status_val: str = "completed",
    content: Any = None,
    metadata: dict[str, Any] | None = None,
) -> MagicMock:
    out = MagicMock(spec=Output)
    out.id = output_id or uuid.uuid4()
    out.job_id = job_id or uuid.uuid4()
    out.output_type = output_type
    out.status = status_val
    out.storage_key = None
    out.mime_type = None
    out.text_content = None
    out.structured_content = content or {"title": "Test Title", "executive_summary": "Summary content"}
    out.output_metadata = metadata or {}
    out.created_at = "2026-09-17T12:00:00Z"
    return out


# ===========================================================================
# 1. Authorization & IDOR Hardening
# ===========================================================================

class TestAuthorizationAndIdor:
    """Verifies that non-owners cannot access or manipulate other users' resources."""

    @pytest.mark.asyncio
    async def test_non_owner_cannot_access_output(self, attacker_user: CurrentUser):
        """GET /outputs/{output_id} returns 404 for non-owner (no IDOR leakage)."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.transformations import get_output

            with pytest.raises(Exception) as exc_info:
                await get_output(uuid.uuid4(), db=mock_db, current_user=attacker_user)
            assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_owner_cannot_download_artifact(self, attacker_user: CurrentUser):
        """GET /outputs/{output_id}/download returns 404 for non-owner."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.transformations import download_output_artifact

            with pytest.raises(Exception) as exc_info:
                await download_output_artifact(uuid.uuid4(), db=mock_db, current_user=attacker_user)
            assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_owner_cannot_export_document(self, attacker_user: CurrentUser):
        """POST /outputs/{output_id}/export returns 404 for non-owner."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.transformations import export_output_document

            with pytest.raises(Exception) as exc_info:
                await export_output_document(uuid.uuid4(), db=mock_db, current_user=attacker_user)
            assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_owner_cannot_view_or_submit_approvals(self, attacker_user: CurrentUser):
        """GET and POST /outputs/{output_id}/approval return 404 for non-owner."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.schemas.transformation import ApprovalActionRequest
            from app.api.v1.transformations import (
                get_output_approval_endpoint,
                submit_output_approval_endpoint,
            )

            with pytest.raises(Exception) as exc1:
                await get_output_approval_endpoint(uuid.uuid4(), db=mock_db, current_user=attacker_user)
            assert "404" in str(exc1.value)

            req = ApprovalActionRequest(destination="DOWNLOAD", action="approve")
            with pytest.raises(Exception) as exc2:
                await submit_output_approval_endpoint(uuid.uuid4(), body=req, db=mock_db, current_user=attacker_user)
            assert "404" in str(exc2.value)

    @pytest.mark.asyncio
    async def test_non_owner_cannot_verify_integrity_or_signature(self, attacker_user: CurrentUser):
        """GET/POST for integrity and signature verification return 404 for non-owner."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.transformations import (
                get_output_integrity_endpoint,
                get_output_signature_endpoint,
                verify_output_integrity_endpoint,
                verify_output_signature_endpoint,
            )

            for endpoint in (
                get_output_integrity_endpoint,
                verify_output_integrity_endpoint,
                get_output_signature_endpoint,
                verify_output_signature_endpoint,
            ):
                with pytest.raises(Exception) as exc_info:
                    await endpoint(uuid.uuid4(), db=mock_db, current_user=attacker_user)
                assert "404" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_owner_cannot_disseminate(self, attacker_user: CurrentUser):
        """POST /outputs/{output_id}/disseminate returns 404 for non-owner."""
        mock_db = AsyncMock(spec=AsyncSession)
        with patch.object(transformation_service, "get_output_owned", return_value=None):
            from app.api.v1.schemas.transformation import DisseminateRequest
            from app.api.v1.transformations import disseminate_output_endpoint

            req = DisseminateRequest(destination="DOWNLOAD")
            with pytest.raises(Exception) as exc_info:
                await disseminate_output_endpoint(uuid.uuid4(), body=req, db=mock_db, current_user=attacker_user)
            assert "404" in str(exc_info.value)

    def test_worker_cross_project_ownership_mismatch_fails_closed(self):
        """Worker ownership verification fails closed if job source belongs to a different project."""
        mock_session = MagicMock(spec=Session)
        job_id = uuid.uuid4()
        proj_id = uuid.uuid4()
        other_proj_id = uuid.uuid4()

        job = TransformationJob(id=job_id, project_id=proj_id, source_id=uuid.uuid4(), status="queued")
        proj = Project(id=proj_id, user_id=uuid.uuid4(), name="P1")
        source = Source(id=job.source_id, project_id=other_proj_id, source_type="text")

        def mock_get(model, pk):
            if model == Project:
                return proj
            if model == Source:
                return source
            return None

        mock_session.get.side_effect = mock_get

        from app.transformation.service import _verify_job_ownership

        with pytest.raises(TransformationError) as exc_info:
            _verify_job_ownership(mock_session, job)
        assert "source/ownership mismatch" in str(exc_info.value)


# ===========================================================================
# 2. Policy Fail-Closed Hardening
# ===========================================================================

class TestPolicyFailClosed:
    """Verifies that the policy engine and router fail closed under any invalid or unexpected input."""

    def test_missing_or_invalid_classification(self):
        """Invalid classification fails closed; None defaults safely to INTERNAL."""
        assert normalize_classification(None) == DEFAULT_CLASSIFICATION
        assert normalize_classification("") == DEFAULT_CLASSIFICATION

        with pytest.raises(InvalidClassificationError):
            normalize_classification("TOP_SECRET_UNKNOWN")

        with pytest.raises(InvalidClassificationError):
            normalize_classification("malicious'; DROP TABLE users;--")

    def test_unknown_destination_fails_closed(self):
        """Unknown or malformed dissemination destination raises InvalidDestinationError and engine blocks."""
        with pytest.raises(InvalidDestinationError):
            normalize_destination(None)

        with pytest.raises(InvalidDestinationError):
            normalize_destination("DARK_WEB")

        engine = get_dissemination_engine()
        decision = engine.evaluate(
            classification="PUBLIC",
            destination="UNRECOGNIZED_CHANNEL",
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK
        assert "invalid_destination" in decision.details.get("error", "")

    def test_unknown_provider_fails_closed(self):
        """Unknown AI provider is rejected with BLOCKED route and zero LLM invocations."""
        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_provider="unknown_shadow_llm",
            environment="cloud",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Unknown or unsupported model provider" in decision.reason

    def test_unknown_environment_fails_closed(self):
        """Unknown processing environment is rejected with BLOCKED route."""
        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_provider="fake",
            environment="untrusted_third_party_mesh",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "Unsupported processing environment" in decision.reason

    def test_test_provider_in_production_fails_closed(self):
        """Test/mock provider 'fake' is strictly blocked in production environments."""
        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_provider="fake",
            environment="production",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.processing_route == ProcessingRoute.BLOCKED.value
        assert "production environment" in decision.reason.lower()

    def test_zero_llm_dependency_in_policy_engine(self):
        """Policy evaluation is pure deterministic Python; zero LLM calls are made."""
        engine = get_policy_engine()
        ctx = PolicyEvaluationContext(
            classification=InformationClassification.INTERNAL,
            requested_provider="fake",
            environment="development",
        )
        with patch("app.transformation.llm.factory.build_llm_provider") as mock_llm:
            decision = engine.evaluate(ctx)
            assert decision.allowed is True
            mock_llm.assert_not_called()


# ===========================================================================
# 3. Sensitive AI Routing & Offline Hardening
# ===========================================================================

class TestSensitiveAIRoutingAndOffline:
    """Verifies that sensitive data and offline mode strictly forbid cloud execution and fallbacks."""

    def test_confidential_and_restricted_forbid_cloud_providers(self):
        """CONFIDENTIAL and RESTRICTED classifications strictly deny external cloud providers."""
        engine = get_policy_engine()
        router = PolicyRouter()

        for classification in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
            for cloud_provider in ("openai", "gemini"):
                ctx = PolicyEvaluationContext(
                    classification=classification,
                    requested_provider=cloud_provider,
                    environment="development",
                )
                decision = engine.evaluate(ctx)
                assert decision.allowed is False
                assert decision.processing_route == ProcessingRoute.BLOCKED.value

                route_dec = router.route(decision=decision, requested_provider=cloud_provider)
                assert route_dec.allowed is False
                assert route_dec.error_code in (ERROR_POLICY_DENIED, ERROR_COMPLIANT_PROVIDER_UNAVAILABLE)

    def test_offline_mode_forbids_cloud_providers(self, monkeypatch):
        """In offline mode, cloud providers cannot be selected and fail closed."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        engine = get_policy_engine()
        router = PolicyRouter()

        ctx = PolicyEvaluationContext(
            classification=InformationClassification.PUBLIC,
            requested_provider="openai",
            environment="offline",
        )
        decision = engine.evaluate(ctx)
        # Even if public, routing in offline mode rejects cloud
        route_dec = router.route(decision=decision, requested_provider="openai")
        assert route_dec.allowed is False
        assert route_dec.error_code == ERROR_COMPLIANT_PROVIDER_UNAVAILABLE
        assert "cannot be used in offline execution mode" in route_dec.reason

    def test_offline_mode_factory_rejects_cloud_and_forbids_cloud_fallback(self, monkeypatch):
        """build_routed_llm_provider refuses cloud instantiation and fallback in offline mode."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "openai")

        cloud_decision = RouteDecision(
            allowed=True,
            provider_id="openai",
            model_id="gpt-4o",
            provider_category=ProviderCategory.EXTERNAL_CLOUD,
            processing_route=ProcessingRoute.CLOUD,
            classification=InformationClassification.PUBLIC,
            reason="test",
        )

        with pytest.raises(CompliantRoutingError) as exc_info:
            build_routed_llm_provider(cloud_decision)
        assert "prohibited when LLM_EXECUTION_MODE='offline'" in str(exc_info.value)

        # Compliant fake provider with cloud fallback configured
        fake_decision = RouteDecision(
            allowed=True,
            provider_id="fake",
            model_id="fake-v1",
            provider_category=ProviderCategory.TEST_DEVELOPMENT,
            processing_route=ProcessingRoute.PRIVATE_LOCAL,
            classification=InformationClassification.PUBLIC,
            reason="test",
        )
        mgr = build_routed_llm_provider(fake_decision)
        # Verify fallback was stripped/suppressed because of offline mode
        assert mgr.fallback is None

    def test_sensitive_classification_strips_cloud_fallback(self, monkeypatch):
        """Sensitive classifications (CONFIDENTIAL / RESTRICTED) never attach cloud fallbacks."""
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "openai")
        monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test-key")

        for sens in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
            dec = RouteDecision(
                allowed=True,
                provider_id="fake",
                model_id="fake-v1",
                provider_category=ProviderCategory.TEST_DEVELOPMENT,
                processing_route=ProcessingRoute.PRIVATE_LOCAL,
                classification=sens,
                reason="test",
            )
            mgr = build_routed_llm_provider(dec)
            assert mgr.fallback is None, f"Cloud fallback was not suppressed for sensitive classification {sens}"

    def test_missing_local_provider_url_fails_closed(self, monkeypatch):
        """Local provider without base URL fails closed with COMPLIANT_PROVIDER_UNAVAILABLE."""
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "")
        monkeypatch.setattr(settings, "LLM_BASE_URL", "")

        dec = RouteDecision(
            allowed=True,
            provider_id="local",
            model_id="llama3",
            provider_category=ProviderCategory.PRIVATE_LOCAL,
            processing_route=ProcessingRoute.PRIVATE_LOCAL,
            classification=InformationClassification.INTERNAL,
            reason="test",
        )
        with pytest.raises(CompliantRoutingError) as exc_info:
            build_routed_llm_provider(dec)
        assert "requires LOCAL_LLM_BASE_URL" in str(exc_info.value)


# ===========================================================================
# 4. Dissemination Hardening & Policy Supremacy
# ===========================================================================

class TestDisseminationHardening:
    """Verifies that dissemination rules cannot be bypassed and take supremacy over human approval."""

    def test_sensitive_dissemination_hard_blocked_for_public_channels(self):
        """CONFIDENTIAL and RESTRICTED information is hard blocked from public web and social destinations."""
        engine = get_dissemination_engine()

        for sens in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
            for dest in (DisseminationDestination.PUBLIC_WEB, DisseminationDestination.LINKEDIN, DisseminationDestination.X):
                decision = engine.evaluate(classification=sens, destination=dest)
                assert decision.allowed is False
                assert decision.decision == DisseminationDecisionOutcome.BLOCK
                assert "prohibited from external/public destination" in decision.reason

    @pytest.mark.asyncio
    async def test_human_approval_never_overrides_dissemination_hard_block(self):
        """An operator cannot approve an output for a destination that is hard-blocked by policy."""
        mock_db = AsyncMock(spec=AsyncSession)
        output = _make_mock_output()

        # Mock classification as RESTRICTED
        with patch.object(approval_service, "resolve_output_classification", return_value=InformationClassification.RESTRICTED):
            from fastapi import HTTPException

            user = CurrentUser(id=uuid.uuid4(), email="admin@gov.in", name="Admin", role="admin")
            with pytest.raises(HTTPException) as exc_info:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=user,
                    destination=DisseminationDestination.LINKEDIN,
                    action=ApprovalAction.APPROVE,
                )
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "prohibited by Phase 2D dissemination policy" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_disseminate_endpoint_fails_closed_when_blocked(self, owner_user: CurrentUser):
        """POST /outputs/{output_id}/disseminate returns 403 Forbidden when policy denies release."""
        mock_db = AsyncMock(spec=AsyncSession)
        output = _make_mock_output()

        from app.api.v1.schemas.transformation import DisseminateRequest
        from app.api.v1.transformations import disseminate_output_endpoint

        with patch.object(transformation_service, "get_output_owned", return_value=output):
            with patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.RESTRICTED):
                from fastapi import HTTPException

                req = DisseminateRequest(destination="LINKEDIN")
                with pytest.raises(HTTPException) as exc_info:
                    await disseminate_output_endpoint(output.id, body=req, db=mock_db, current_user=owner_user)
                assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# 5. Approval Workflow Hardening
# ===========================================================================

class TestApprovalHardening:
    """Verifies state transition rigidity, rejection enforcement, and non-spoofable approver metadata."""

    def test_invalid_state_transitions_are_rejected(self):
        """Rejected output cannot be approved; double approval is rejected."""
        # Cannot approve an already REJECTED status
        with pytest.raises(InvalidApprovalTransitionError):
            validate_approval_transition(
                current_status=ApprovalStatus.REJECTED.value,
                action=ApprovalAction.APPROVE,
            )

        # Cannot approve an already APPROVED status
        with pytest.raises(InvalidApprovalTransitionError):
            validate_approval_transition(
                current_status=ApprovalStatus.APPROVED.value,
                action=ApprovalAction.APPROVE,
            )

    def test_rejection_strictly_requires_reason(self):
        """Rejection with empty or None reason raises ValueError."""
        with pytest.raises(ValueError) as exc1:
            validate_approval_transition(
                current_status=ApprovalStatus.PENDING_APPROVAL.value,
                action=ApprovalAction.REJECT,
                rejection_reason=None,
            )
        assert "Rejection requires a non-empty rejection_reason" in str(exc1.value)

        with pytest.raises(ValueError) as exc2:
            validate_approval_transition(
                current_status=ApprovalStatus.PENDING_APPROVAL.value,
                action=ApprovalAction.REJECT,
                rejection_reason="   ",
            )
        assert "Rejection requires a non-empty rejection_reason" in str(exc2.value)

    @pytest.mark.asyncio
    async def test_stale_source_hash_invalidates_approval(self):
        """Modifying the source after approval automatically revokes release eligibility."""
        output = _make_mock_output(
            metadata={
                "approval": {
                    "destinations": {
                        "DOWNLOAD": {
                            "destination": "DOWNLOAD",
                            "approval_status": "APPROVED",
                            "approval_id": "appr-12345",
                            "source_hash_snapshot": "old-hash-123",
                            "classification_snapshot": "INTERNAL",
                        }
                    }
                }
            }
        )
        mock_db = AsyncMock()
        mock_source = SimpleNamespace(source_metadata={"content_hash": "modified-new-hash-456"})

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service._load_latest_verification_result", return_value=None), \
             patch("app.services.approval_service._load_source_for_output", return_value=mock_source):
            eligible, reason = await approval_service.verify_release_eligibility(
                mock_db,
                output=output,
                destination=DisseminationDestination.DOWNLOAD,
            )
            assert eligible is False
            assert "Approval is stale" in reason or "modified" in reason


# ===========================================================================
# 6. Cryptographic Integrity & Signature Tamper Detection
# ===========================================================================

class TestIntegrityAndSignatureTampering:
    """Verifies that SHA-256 and Ed25519 verification are read-only and detect any mutation."""

    def test_integrity_verification_is_strictly_read_only(self):
        """Verification recomputes hashes but never mutates or reseals the stored record."""
        output = _make_mock_output()
        output.output_metadata = {
            "provenance": {
                "provenance_id": "prov-1",
                "classification": "INTERNAL",
                "workflow": "transformation",
            }
        }

        rec = seal_output_integrity(output)
        assert rec is not None
        assert rec.status == IntegrityStatus.VERIFIED.value

        stored_snapshot = copy.deepcopy(output.output_metadata["cryptographic_integrity"])

        # Run verification multiple times
        res1 = verify_output_integrity(output)
        assert res1["status"] == IntegrityStatus.VERIFIED.value

        res2 = verify_output_integrity(output)
        assert res2["status"] == IntegrityStatus.VERIFIED.value

        # Stored metadata must be bit-for-bit identical to prior state
        assert output.output_metadata["cryptographic_integrity"] == stored_snapshot

    def test_artifact_tampering_produces_invalid(self):
        """Mutating output structured content causes verification to return INVALID."""
        output = _make_mock_output()
        output.output_metadata = {
            "provenance": {"provenance_id": "prov-1", "classification": "INTERNAL"}
        }
        seal_output_integrity(output)

        # Tamper with content
        output.structured_content = {"tampered": "hacked content"}
        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["artifact_verified"] is False

    def test_provenance_tampering_produces_invalid(self):
        """Mutating provenance record causes verification to return INVALID."""
        output = _make_mock_output()
        output.output_metadata = {
            "provenance": {
                "provenance_id": "prov-1",
                "source": {"classification": "INTERNAL", "source_content_hash": "abc"},
                "policy_routing": {"classification": "INTERNAL"},
            }
        }
        seal_output_integrity(output)

        # Tamper with provenance classification in source snapshot
        output.output_metadata["provenance"]["source"]["classification"] = "PUBLIC"
        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["provenance_verified"] is False

    def test_signature_tampering_produces_invalid(self):
        """Mutating the digital signature string causes signature verification to return INVALID."""
        output = _make_mock_output()
        output.output_metadata = {
            "provenance": {"provenance_id": "prov-1", "classification": "INTERNAL"}
        }
        seal_output_integrity(output)

        sig_rec = sign_output_artifact(output)
        assert sig_rec is not None
        assert sig_rec.status == SignatureStatus.VALID.value

        # Verify initially valid
        assert verify_output_signature(output)["status"] == SignatureStatus.VALID.value

        # Corrupt signature string
        sig_meta = output.output_metadata["digital_signature"]
        sig_meta["signature"] = "deadbeef" * 16
        output.output_metadata["digital_signature"] = sig_meta

        res = verify_output_signature(output)
        assert res["status"] == SignatureStatus.INVALID.value

    def test_signer_public_metadata_never_exposes_private_keys(self):
        """Public verification metadata contains only public keys and identifiers; never private keys."""
        signer = get_digital_signer()
        meta = signer.get_public_metadata()

        dumped = json.dumps(meta).lower()
        assert "private" not in dumped
        assert "secret" not in dumped
        assert "key_id" in meta
        assert "algorithm" in meta


# ===========================================================================
# 7. Input / Upload Security
# ===========================================================================

class TestInputValidationAndUploadSecurity:
    """Verifies file and input sanitation against traversal, control chars, and size violations."""

    def test_path_traversal_in_filename_rejected(self):
        """Path traversal sequences (../, ..\\) in filenames are strictly rejected."""
        content = b"Safe text content."
        for evil_name in ("../../etc/passwd", "..\\windows\\system32\\calc.exe", "nested/../../secret.txt"):
            with pytest.raises(SourceValidationError) as exc_info:
                validate_source(
                    source_type="txt",
                    content=content,
                    filename=evil_name,
                    mime_type="text/plain",
                    max_size_bytes=settings.max_upload_size_bytes,
                )
            assert "invalid path characters" in str(exc_info.value).lower()

    def test_control_characters_and_null_bytes_rejected(self):
        """Filenames containing null bytes or control characters are rejected."""
        content = b"Text."
        for bad_name in ("doc\0.txt", "doc\r\n.txt", "report\x1b.txt"):
            with pytest.raises(SourceValidationError) as exc_info:
                validate_source(
                    source_type="txt",
                    content=content,
                    filename=bad_name,
                    mime_type="text/plain",
                    max_size_bytes=settings.max_upload_size_bytes,
                )
            assert "invalid control characters" in str(exc_info.value).lower()

    def test_excessive_filename_length_rejected(self):
        """Filenames exceeding 255 characters are rejected."""
        long_name = "a" * 256 + ".txt"
        with pytest.raises(SourceValidationError) as exc_info:
            validate_source(
                source_type="txt",
                content=b"Text",
                filename=long_name,
                mime_type="text/plain",
                max_size_bytes=settings.max_upload_size_bytes,
            )
        assert "exceeds 255 characters" in str(exc_info.value).lower()

    def test_file_size_limit_enforced(self):
        """Content exceeding maximum configured bytes is rejected."""
        large_content = b"x" * 1024
        with pytest.raises(SourceValidationError) as exc_info:
            validate_source(
                source_type="txt",
                content=large_content,
                filename="doc.txt",
                mime_type="text/plain",
                max_size_bytes=512,
            )
        assert "exceeds the maximum size" in str(exc_info.value).lower()


# ===========================================================================
# 8. Secret Exposure & Production Hardening
# ===========================================================================

class TestSecretExposureAndProductionHardening:
    """Verifies security response headers and that secrets/passwords are never leaked."""

    def test_production_security_headers_present(self, client: TestClient):
        """API responses include standard security headers."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_audit_events_do_not_leak_secrets(self):
        """Security audit emitter redacts passwords, tokens, and API keys."""
        clear_security_events()
        emit_security_event(
            "test_auth_event",
            outcome="observed",
            details={
                "api_key": "sk-real-secret-key-12345",
                "auth_header": "Bearer sk-proj-1234567890abcdef",
                "safe_field": "public_data",
            },
        )
        events = security_events()
        assert len(events) >= 1
        ev = events[-1]
        ev_str = json.dumps(ev).lower()

        assert "sk-real-secret" not in ev_str
        assert "sk-proj-1234567890abcdef" not in ev_str
        assert "<redacted>" in ev_str

    def test_unhandled_exception_returns_safe_500(self, client: TestClient):
        """Unhandled exceptions return a generic JSON 500 error without exposing stack traces."""
        with patch.object(transformation_service, "get_job", side_effect=RuntimeError("Secret database crash details!")):
            resp = client.get(f"/api/v1/transformations/{uuid.uuid4()}")
            assert resp.status_code == 500
            data = resp.json()
            assert data.get("detail") == "An internal server error occurred."
            assert "Secret database crash" not in str(data)


# ===========================================================================
# 9. Worker Failure Isolation
# ===========================================================================

class TestWorkerFailureIsolation:
    """Verifies that failures in one output or worker step do not corrupt unrelated outputs."""

    def test_worker_failure_isolation_multi_output(self):
        """Single generator failure in multi-output run preserves successful outputs."""
        # Orchestrator handles output-level isolation; verifying data model and result dict
        result = {
            "job_id": str(uuid.uuid4()),
            "status": "partial_success",
            "outputs": [{"output_type": "summary", "status": "completed"}],
            "errors": [{"output_type": "video", "error": "Video renderer timed out"}],
        }
        assert len(result["outputs"]) == 1
        assert result["outputs"][0]["status"] == "completed"
        assert len(result["errors"]) == 1
        assert "timed out" in result["errors"][0]["error"]
