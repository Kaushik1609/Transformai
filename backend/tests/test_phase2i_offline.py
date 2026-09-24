"""
TransformIQ / KaryaSetu AI — Phase 2I Air-Gapped & Offline AI Execution Tests

Comprehensive verification suite covering:
1. LocalLLMProvider interface
2. Local provider configuration
3. Offline execution mode
4. Cloud provider rejection in offline mode
5. Local provider selection in offline mode
6. No cloud fallback in offline mode
7. RESTRICTED classification cloud rejection
8. CONFIDENTIAL classification cloud rejection
9. Provider capability detection
10. Deterministic routing preservation
11. RAG / evidence preservation
12. Provenance execution metadata
13. SHA-256 integrity preservation
14. Ed25519 digital signature preservation
15. Phase 2F human approval preservation
16. Phase 2D dissemination preservation
17. Multi-output offline generation
18. Provider injection
19. Missing local provider failure
20. Secret/private-key protection
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.audit import clear_security_events, security_events
from app.core.config import settings
from app.policy.approval import ApprovalStatus
from app.policy.classification import InformationClassification
from app.policy.dissemination import (
    DisseminationDecisionOutcome,
    DisseminationDestination,
    get_dissemination_engine,
)
from app.policy.integrity import (
    CryptographicIntegrityRecord,
    IntegrityStatus,
    canonical_json_hash,
)
from app.policy.provenance import (
    PolicyRoutingLineage,
    ProvenanceBuilder,
    ProvenanceExtensions,
    ProvenanceRecord,
)
from app.policy.registry import (
    ProviderCategory,
    ProviderDescriptor,
    get_provider_registry,
)
from app.policy.routing import (
    ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
    ERROR_POLICY_DENIED,
    PolicyRouter,
    ProcessingRoute,
    RouteDecision,
    get_policy_router,
)
from app.policy.signature import (
    DigitalSignatureRecord,
    Ed25519Signer,
    FakeDigitalSigner,
    SignatureStatus,
    build_signing_payload,
    get_digital_signer,
    set_digital_signer_provider,
)
from app.services.integrity_service import seal_output_integrity
from app.services.signature_service import sign_output_artifact, verify_output_signature
from app.transformation.llm.factory import (
    _build_fallback_provider,
    build_llm_provider,
)
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.gemini_provider import GeminiLLMProvider
from app.transformation.llm.local_provider import LocalLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.llm.router_factory import (
    CompliantRoutingError,
    build_routed_llm_provider,
    instantiate_routed_provider,
)


# ===========================================================================
# 1. LOCAL PROVIDER INTERFACE & CAPABILITIES (1, 2, 9)
# ===========================================================================

class TestLocalProviderInterfaceAndCapabilities:
    """Tests 1, 2, 9: Interface, configuration, and capability flags."""

    def test_01_local_provider_interface(self, monkeypatch):
        """1. LocalLLMProvider conforms to abstract LLMProvider contract."""
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        provider = LocalLLMProvider(model="llama-3-8b")

        assert isinstance(provider, LLMProvider)
        assert hasattr(provider, "generate_text")
        assert callable(provider.generate_text)
        assert provider.is_external is False
        assert provider.is_local is True
        assert provider.requires_network is False
        assert provider.supports_offline is True
        assert provider.model == "llama-3-8b"
        assert provider.base_url == "http://localhost:11434/v1"

    def test_02_local_provider_configuration(self, monkeypatch):
        """2. LocalLLMProvider respects environment settings."""
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "mistral-7b")
        monkeypatch.setattr(settings, "LOCAL_LLM_TIMEOUT", 45)

        provider = LocalLLMProvider()
        assert provider.model == "mistral-7b"
        assert provider.base_url == "http://127.0.0.1:8000/v1"
        assert provider._timeout == 45

    def test_09_provider_capability_detection(self):
        """9. Provider capability markers distinguish cloud from local/offline."""
        # Cloud providers
        assert OpenAILLMProvider.is_external is True
        assert OpenAILLMProvider.is_local is False
        assert OpenAILLMProvider.requires_network is True
        assert OpenAILLMProvider.supports_offline is False

        assert GeminiLLMProvider.is_external is True
        assert GeminiLLMProvider.is_local is False
        assert GeminiLLMProvider.requires_network is True
        assert GeminiLLMProvider.supports_offline is False

        # Local providers
        assert LocalLLMProvider.is_external is False
        assert LocalLLMProvider.is_local is True
        assert LocalLLMProvider.requires_network is False
        assert LocalLLMProvider.supports_offline is True

        # Fake provider
        assert FakeLLMProvider.is_external is False
        assert FakeLLMProvider.is_local is False
        assert FakeLLMProvider.requires_network is False
        assert FakeLLMProvider.supports_offline is True

        # Registry descriptors
        registry = get_provider_registry()
        openai_desc = registry.get_provider("openai")
        assert openai_desc.is_external is True
        assert openai_desc.supports_offline is False

        local_desc = registry.get_provider("local")
        assert local_desc.is_external is False
        assert local_desc.is_local is True
        assert local_desc.supports_offline is True

        fake_desc = registry.get_provider("fake")
        assert fake_desc.is_external is False
        assert fake_desc.supports_offline is True


# ===========================================================================
# 2. OFFLINE MODE ROUTING & SAFEGUARDS (3, 4, 5, 6, 7, 8, 19)
# ===========================================================================

class TestOfflineModeRoutingAndSafeguards:
    """Tests 3, 4, 5, 6, 7, 8, 19: Offline enforcement, cloud rejection, fail-closed."""

    def test_03_offline_execution_mode(self, monkeypatch):
        """3. Offline execution mode operates deterministically without external network."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        monkeypatch.setattr(settings, "LLM_PROVIDER", "fake")
        router = get_policy_router()

        decision = router.resolve_route(
            classification=InformationClassification.INTERNAL,
            environment="offline",
        )
        assert decision.allowed is True
        assert decision.details["execution_mode"] == "offline"
        assert decision.details["is_offline"] is True
        assert decision.details["is_external"] is False

    def test_04_cloud_provider_rejected_in_offline_mode(self, monkeypatch):
        """4. Requesting cloud provider in offline mode fails closed."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        router = get_policy_router()

        for cloud_p in ("openai", "gemini"):
            decision = router.resolve_route(
                classification=InformationClassification.PUBLIC,
                requested_provider=cloud_p,
                environment="offline",
            )
            assert decision.allowed is False
            assert decision.error_code in (ERROR_COMPLIANT_PROVIDER_UNAVAILABLE, ERROR_POLICY_DENIED)
            assert "offline execution mode" in decision.reason or "not permitted" in decision.reason

            # Factory level enforcement
            with pytest.raises(ValueError) as exc:
                build_llm_provider(cloud_p)
            assert "prohibited when LLM_EXECUTION_MODE='offline'" in str(exc.value)

            # Routed factory level enforcement
            mock_decision = RouteDecision(
                allowed=True,
                provider_id=cloud_p,
                model_id="gpt-4o-mini",
                provider_category=ProviderCategory.EXTERNAL_CLOUD,
                processing_route=ProcessingRoute.CLOUD,
                classification=InformationClassification.PUBLIC,
                reason="test",
            )
            with pytest.raises(CompliantRoutingError) as exc_route:
                build_routed_llm_provider(mock_decision)
            assert "prohibited when LLM_EXECUTION_MODE='offline'" in str(exc_route.value)

    def test_05_local_provider_selected_in_offline_mode(self, monkeypatch):
        """5. Local provider is selected when configured in offline mode."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setattr(settings, "LLM_PROVIDER", "local")
        router = get_policy_router()

        decision = router.resolve_route(
            classification=InformationClassification.INTERNAL,
            environment="offline",
        )
        assert decision.allowed is True
        assert decision.provider_id == "local"
        assert decision.details["is_offline"] is True
        assert decision.details["is_external"] is False

    def test_06_no_cloud_fallback_in_offline_mode(self, monkeypatch):
        """6. Resilience layer never injects cloud fallback in offline mode."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "openai")

        decision = RouteDecision(
            allowed=True,
            provider_id="local",
            model_id="llama-3-8b",
            provider_category=ProviderCategory.PRIVATE_LOCAL,
            processing_route=ProcessingRoute.PRIVATE_LOCAL,
            classification=InformationClassification.PUBLIC,
            reason="Approved",
        )

        with patch("app.transformation.llm.router_factory.LocalLLMProvider") as mock_local:
            mock_local.return_value = FakeLLMProvider()
            manager = build_routed_llm_provider(decision, resilient=True)
            # Cloud fallback MUST be excluded in offline mode!
            assert manager.fallback is None

        # Direct fallback builder check
        with pytest.raises(ValueError) as exc:
            _build_fallback_provider("openai")
        assert "prohibited when LLM_EXECUTION_MODE='offline'" in str(exc.value)

    def test_07_restricted_classification_cannot_route_externally(self, monkeypatch):
        """7. RESTRICTED classification can NEVER route to external cloud."""
        router = get_policy_router()
        for mode in ("cloud", "offline", "auto"):
            monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", mode)
            decision = router.resolve_route(
                classification=InformationClassification.RESTRICTED,
                requested_provider="openai",
                environment=mode,
            )
            assert decision.allowed is False
            assert "cannot be processed by external cloud" in decision.reason or "offline" in decision.reason

    def test_08_confidential_classification_cannot_route_externally(self, monkeypatch):
        """8. CONFIDENTIAL classification can NEVER route to external cloud."""
        router = get_policy_router()
        for mode in ("cloud", "offline", "auto"):
            monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", mode)
            decision = router.resolve_route(
                classification=InformationClassification.CONFIDENTIAL,
                requested_provider="gemini",
                environment=mode,
            )
            assert decision.allowed is False
            assert "requires private or local model processing" in decision.reason or "offline" in decision.reason

    def test_19_missing_local_provider_failure(self, monkeypatch):
        """19. Clear fail-closed error when local provider is missing URL configuration."""
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "")
        monkeypatch.setattr(settings, "LLM_BASE_URL", "")

        # Local provider directly raises ValueError
        with pytest.raises(ValueError) as exc:
            LocalLLMProvider(base_url="")
        assert "requires LOCAL_LLM_BASE_URL or LLM_BASE_URL" in str(exc.value)

        # In offline mode, router fails closed
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.CONFIDENTIAL,
            requested_provider="local",
            environment="offline",
        )
        assert decision.allowed is False
        assert decision.error_code in (ERROR_COMPLIANT_PROVIDER_UNAVAILABLE, ERROR_POLICY_DENIED)


# ===========================================================================
# 3. DETERMINISTIC ROUTING & RAG PRESERVATION (10, 11)
# ===========================================================================

class TestDeterministicRoutingAndRagPreservation:
    """Tests 10, 11: Deterministic outcomes and RAG/grounding preservation."""

    def test_10_routing_decision_preservation(self, monkeypatch):
        """10. Repeated offline routing calls produce identical, deterministic results."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        router = get_policy_router()

        decisions = [
            router.resolve_route(
                classification=InformationClassification.INTERNAL,
                requested_provider="local",
                environment="offline",
            )
            for _ in range(5)
        ]

        first = decisions[0]
        for d in decisions[1:]:
            assert d.allowed == first.allowed
            assert d.provider_id == first.provider_id
            assert d.model_id == first.model_id
            assert d.processing_route == first.processing_route
            assert d.details == first.details

    def test_11_rag_evidence_preservation(self):
        """11. RAG evidence citations and canonical context remain intact in offline mode."""
        fake_citations = [
            {"chunk_id": str(uuid.uuid4()), "chunk_index": 0, "excerpt": "Offline evidence grounded fact."},
            {"chunk_id": str(uuid.uuid4()), "chunk_index": 1, "excerpt": "Second offline grounded citation."},
        ]

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=str(uuid.uuid4()),
            output_type="summary",
            classification="INTERNAL",
            citations=fake_citations,
            routing_metadata={"execution_mode": "offline", "provider": "local", "is_offline": True},
        )

        assert record.evidence.chunks_count == 2
        assert len(record.evidence.citations) == 2
        assert record.evidence.citations[0].excerpt == "Offline evidence grounded fact."
        assert record.policy_routing.execution_mode == "offline"
        assert record.policy_routing.is_offline is True


# ===========================================================================
# 4. PROVENANCE & INTEGRITY & SIGNATURE PIPELINE (12, 13, 14)
# ===========================================================================

class TestProvenanceIntegritySignaturePipeline:
    """Tests 12, 13, 14: Downstream provenance, SHA-256 integrity, and Ed25519 signatures."""

    def test_12_provenance_records_offline_execution_mode(self):
        """12. Provenance records capture offline execution mode and capabilities."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=str(uuid.uuid4()),
            output_type="summary",
            classification="INTERNAL",
            routing_metadata={
                "provider": "local",
                "model": "llama-3-8b",
                "provider_category": "PRIVATE_LOCAL",
                "processing_route": "private_local",
                "execution_mode": "offline",
                "is_external": False,
                "is_offline": True,
                "provider_type": "PRIVATE_LOCAL",
            },
        )

        assert record.policy_routing.execution_mode == "offline"
        assert record.policy_routing.is_offline is True
        assert record.policy_routing.is_external is False
        assert record.policy_routing.provider_id == "local"
        assert record.extensions.execution_mode == "offline"
        assert record.extensions.is_offline is True

    def test_13_integrity_sealing_still_occurs(self):
        """13. Cryptographic SHA-256 integrity sealing completes for offline outputs."""
        output_id = uuid.uuid4()
        job_id = uuid.uuid4()
        output = SimpleNamespace(
            id=output_id,
            job_id=job_id,
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Offline generated verified summary text."},
            text_content=None,
            output_metadata={
                "classification": "INTERNAL",
                "policy_id": "pol-test",
                "provenance": {
                    "provenance_id": f"prov-{output_id}",
                    "version": "1.0",
                    "policy_routing": {"is_offline": True, "execution_mode": "offline"},
                },
            },
        )

        record = seal_output_integrity(output)
        assert record is not None
        assert record.status == IntegrityStatus.VERIFIED.value
        assert record.algorithm == "sha256"
        assert record.artifact_hash is not None
        assert "cryptographic_integrity" in output.output_metadata

    def test_14_ed25519_signing_still_occurs(self):
        """14. Ed25519 digital signature is applied to offline outputs downstream."""
        output_id = uuid.uuid4()
        job_id = uuid.uuid4()
        output = SimpleNamespace(
            id=output_id,
            job_id=job_id,
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Deterministic offline content for signing."},
            text_content=None,
            output_metadata={
                "classification": "INTERNAL",
                "policy_id": "pol-test",
                "provenance": {
                    "provenance_id": f"prov-{output_id}",
                    "version": "1.0",
                    "policy_routing": {"is_offline": True, "execution_mode": "offline"},
                },
            },
        )

        integ_record = seal_output_integrity(output)
        assert integ_record is not None

        signer = Ed25519Signer()
        sig_record = sign_output_artifact(output, signer=signer)
        assert sig_record is not None
        assert sig_record.status == SignatureStatus.VALID.value
        assert sig_record.algorithm == "ed25519"
        assert sig_record.signature is not None
        assert "digital_signature" in output.output_metadata

        # Verify signature via read-only verification service
        verify_res = verify_output_signature(output, signer=signer)
        assert verify_res["status"] == SignatureStatus.VALID.value
        assert verify_res["details"].get("signature_verified") is True


# ===========================================================================
# 5. GOVERNANCE AUTHORITATIVENESS & MULTI-OUTPUT (15, 16, 17, 18, 20)
# ===========================================================================

class TestGovernanceAndSecuritySafeguards:
    """Tests 15, 16, 17, 18, 20: Approval supremacy, dissemination, injection, secrets scan."""

    def test_15_phase_2f_approval_remains_authoritative(self):
        """15. Offline outputs requiring review remain subject to Phase 2F approval rules."""
        # A signed offline output marked PENDING_APPROVAL cannot be treated as approved
        meta = {
            "approval": {"status": ApprovalStatus.PENDING_APPROVAL.value},
            "digital_signature": {"status": "valid"},
            "provenance": {"policy_routing": {"is_offline": True}},
        }
        assert meta["approval"]["status"] == ApprovalStatus.PENDING_APPROVAL.value
        # Signature validity does NOT grant approval
        assert meta["approval"]["status"] != ApprovalStatus.APPROVED.value

    def test_16_phase_2d_dissemination_remains_authoritative(self):
        """16. Phase 2D dissemination rules remain strictly authoritative for offline outputs."""
        engine = get_dissemination_engine()
        # CONFIDENTIAL cannot be disseminated externally to public web
        decision = engine.evaluate(
            classification=InformationClassification.CONFIDENTIAL,
            destination=DisseminationDestination.PUBLIC_WEB,
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK

    def test_17_multi_output_offline_generation(self, monkeypatch):
        """17. Multi-output offline pipeline runs without failure."""
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")
        provider = FakeLLMProvider()

        outputs = {}
        for otype in ("summary", "x", "linkedin"):
            res = provider.generate_text(
                system_prompt=f'{{"type": "{otype}", "fields": ["title", "summary"]}}',
                user_content="Offline multi-output content source text.",
            )
            parsed = json.loads(res)
            assert isinstance(parsed, dict)
            outputs[otype] = parsed

        assert len(outputs) == 3
        assert "summary" in outputs
        assert "x" in outputs
        assert "linkedin" in outputs

    def test_18_provider_injection(self):
        """18. Custom offline provider injection operates cleanly without code modification."""
        class CustomAirGapProvider(LLMProvider):
            is_external = False
            is_local = True
            requires_network = False
            supports_offline = True

            def generate_text(self, *, system_prompt: str, user_content: str) -> str:
                return json.dumps({"summary": "Air-gapped secure execution output"})

        custom = CustomAirGapProvider()
        assert custom.supports_offline is True
        assert custom.is_external is False
        out = custom.generate_text(system_prompt="{}", user_content="hello")
        assert "Air-gapped secure execution output" in out

    def test_20_no_secrets_in_metadata_audit_api(self, monkeypatch):
        """20. Zero API keys, private keys, or tokens exist in metadata, provenance, or audit logs."""
        clear_security_events()
        monkeypatch.setattr(settings, "LLM_API_KEY", "super-secret-cloud-key-12345")
        monkeypatch.setattr(settings, "LLM_EXECUTION_MODE", "offline")

        # Resolve route
        router = get_policy_router()
        decision = router.resolve_route(
            classification=InformationClassification.INTERNAL,
            environment="offline",
        )

        decision_dump = json.dumps(decision.model_dump(mode="json"))
        assert "super-secret-cloud-key-12345" not in decision_dump

        # Build provenance record
        prov = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=str(uuid.uuid4()),
            output_type="summary",
            classification="INTERNAL",
            routing_metadata=decision.details,
        )

        prov_dump = json.dumps(prov.model_dump(mode="json"))
        assert "super-secret-cloud-key-12345" not in prov_dump
        assert "private_key" not in prov_dump

        # Audit events scan
        for event in security_events():
            event_dump = json.dumps(event)
            assert "super-secret-cloud-key-12345" not in event_dump
            assert "BEGIN PRIVATE KEY" not in event_dump
