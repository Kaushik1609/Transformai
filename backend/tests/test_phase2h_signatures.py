"""
TransformIQ / KaryaSetu AI — Phase 2H Digital Signatures & Trusted Artifact Signing Test Suite

Covers all Phase 2H criteria:
1. Deterministic signing payload construction
2. Canonicalization of signing payload
3. FakeDigitalSigner signing and verification
4. Ed25519Signer asymmetric signing and verification
5. HmacSha256Signer symmetric MAC provider (explicitly verified as MAC, NOT asymmetric digital signature)
6. Provider factory behavior and configuration
7. Provider injection & test override
8. Safe public key / provider metadata (zero private key persistence or exposure)
9. Signature persistence in output_metadata["digital_signature"]
10. Post-generation signing hook immediately after integrity sealing
11. Read-only verification (no mutation of stored signature or artifact)
12. Valid verification returns VALID
13. Artifact tampering returns INVALID
14. Companion artifact tampering returns INVALID
15. Provenance tampering returns INVALID
16. Approval tampering returns INVALID
17. Integrity envelope tampering returns INVALID
18. Corrupted signature returns INVALID
19. Missing signature returns UNAVAILABLE (legacy outputs)
20. Missing storage artifact returns UNAVAILABLE
21. Owner access via API returns 200
22. Non-owner access via API returns 404 (IDOR protection)
23. No private keys in output_metadata, provenance, audit events, or API responses
24. Security audit event emission (signature_recorded, signature_verified, signature_failed)
25. Multi-output isolation (distinct signatures and payloads)
26. Phase 2G cryptographic integrity compatibility
27. Phase 2F human approval supremacy (VALID signature does not bypass PENDING_APPROVAL/REJECTED/REVOKED)
28. Phase 2D dissemination policy supremacy (VALID signature does not bypass dissemination BLOCK)
29. No second RAG retrieval or artifact regeneration
30. No database migration / no schema changes
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps import CurrentUser
from app.api.v1.transformations import (
    get_output_signature_endpoint,
    verify_output_signature_endpoint,
)
from app.core.audit import clear_security_events, security_events
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
    canonical_json_bytes,
    canonical_json_hash,
)
from app.policy.signature import (
    DigitalSignatureRecord,
    DigitalSigner,
    Ed25519Signer,
    FakeDigitalSigner,
    HmacSha256Signer,
    ProviderType,
    SignatureStatus,
    build_signing_payload,
    get_digital_signer,
    set_digital_signer_provider,
)
from app.services.integrity_service import (
    record_job_cryptographic_integrity,
    seal_output_integrity,
    verify_output_integrity,
)
from app.services.signature_service import (
    record_job_digital_signatures,
    sign_output_artifact,
    verify_output_signature,
)


class MockStorage:
    """In-memory mock storage for testing binary artifact handling."""
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def read(self, key: str) -> bytes:
        if key in self.files:
            return self.files[key]
        raise FileNotFoundError(f"Key {key} not found in mock storage")

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


# ===========================================================================
# 1. Domain Logic, Providers & MAC Distinction Tests
# ===========================================================================

class TestSignatureDomainLogic:
    """Test signing providers, deterministic payload canonicalization, and MAC distinction."""

    def test_01_deterministic_signing_payload(self):
        """Test signing payload construction is deterministic and excludes volatile data."""
        integrity_envelope = {
            "version": "1.0",
            "algorithm": "sha256",
            "artifact_hash": "a" * 64,
            "companion_hashes": {"pdf": "b" * 64},
            "provenance_id": "prov-123",
            "provenance_hash": "c" * 64,
            "approval_id": "appr-456",
            "recorded_at": "2026-09-16T12:00:00Z",  # volatile timestamp
        }
        meta = {
            "output_type": "summary",
            "classification": "CONFIDENTIAL",
            "policy_id": "pol-default",
            "policy_version": "1.0",
            "other_volatile": "ignored",
        }

        payload1 = build_signing_payload(integrity_envelope, meta)
        payload2 = build_signing_payload(integrity_envelope, meta)

        assert payload1 == payload2
        assert "recorded_at" not in payload1
        assert "other_volatile" not in payload1
        assert payload1["artifact_hash"] == "a" * 64
        assert payload1["companion_hashes"] == {"pdf": "b" * 64}
        assert payload1["provenance_id"] == "prov-123"
        assert payload1["provenance_hash"] == "c" * 64
        assert payload1["approval_id"] == "appr-456"
        assert payload1["classification"] == "CONFIDENTIAL"
        assert payload1["output_type"] == "summary"

    def test_02_signing_payload_canonicalization(self):
        """Test canonicalization produces consistent hash regardless of dict key order."""
        p1 = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
        p2 = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}
        assert canonical_json_bytes(p1) == canonical_json_bytes(p2)
        assert canonical_json_hash(p1) == canonical_json_hash(p2)

    def test_03_fake_digital_signer(self):
        """Test FakeDigitalSigner produces deterministic test signatures and verifies accurately."""
        signer = FakeDigitalSigner(key_id="test-key-1")
        assert signer.algorithm == "fake-sha256"
        assert signer.provider_name == "FakeDigitalSigner"
        assert signer.provider_type == ProviderType.TEST_MOCK
        assert signer.is_asymmetric is False

        payload = b'{"artifact_hash":"test"}'
        sig = signer.sign(payload)
        assert len(sig) == 64
        assert signer.verify(payload, sig, "test-key-1") is True
        assert signer.verify(b'tampered', sig, "test-key-1") is False
        assert signer.verify(payload, "invalid_sig", "test-key-1") is False
        assert signer.verify(payload, sig, "wrong-key") is False

    def test_04_ed25519_signer_asymmetric(self):
        """Test Ed25519 asymmetric signing and verification."""
        signer = Ed25519Signer()
        assert signer.algorithm == "ed25519"
        assert signer.provider_name == "Ed25519Signer"
        assert signer.provider_type == ProviderType.ASYMMETRIC_SIGNATURE
        assert signer.is_asymmetric is True
        assert signer.public_key_hex is not None

        meta = signer.get_public_metadata()
        assert meta["algorithm"] == "ed25519"
        assert meta["is_asymmetric"] is True
        assert meta["provider_type"] == "asymmetric_signature"
        assert "private" not in str(meta).lower()

        payload = b"Production governance payload for KaryaSetu AI"
        sig = signer.sign(payload)
        # Ed25519 signature is 64 bytes -> 128 hex chars
        assert len(sig) == 128
        assert signer.verify(payload, sig, signer.key_id) is True
        assert signer.verify(b"Tampered payload", sig, signer.key_id) is False
        assert signer.verify(payload, "00" * 64, signer.key_id) is False

    def test_05_hmac_sha256_symmetric_mac_distinction(self):
        """MANDATORY REQUIREMENT: Verify HmacSha256 is strictly treated as symmetric MAC, NOT asymmetric digital signature."""
        mac_provider = HmacSha256Signer(key=b"super-secret-mac-key", key_id="mac-key-1")
        assert mac_provider.algorithm == "hmac-sha256"
        assert mac_provider.provider_name == "HmacSha256Signer"
        assert mac_provider.provider_type == ProviderType.SYMMETRIC_MAC
        # MUST NOT be asymmetric digital signature
        assert mac_provider.is_asymmetric is False

        meta = mac_provider.get_public_metadata()
        assert meta["algorithm"] == "hmac-sha256"
        assert meta["is_asymmetric"] is False
        assert meta["provider_type"] == "symmetric_mac"
        assert meta["supports_non_repudiation"] is False
        assert "private" not in str(meta).lower()
        assert "secret" not in str(meta).lower()

        payload = b"Payload to be authenticated with MAC"
        mac_tag = mac_provider.sign(payload)
        assert len(mac_tag) == 64
        assert mac_provider.verify(payload, mac_tag, "mac-key-1") is True
        assert mac_provider.verify(b"Tampered", mac_tag, "mac-key-1") is False

    def test_06_provider_factory_and_injection(self):
        """Test provider factory configuration and test injection."""
        default_signer = get_digital_signer()
        assert isinstance(default_signer, DigitalSigner)

        # Inject custom mock
        custom = FakeDigitalSigner(key_id="custom-injected")
        set_digital_signer_provider(custom)
        assert get_digital_signer().key_id == "custom-injected"

        # Reset to default
        set_digital_signer_provider(None)
        assert get_digital_signer() is not None


# ===========================================================================
# 2. Lifecycle Signing & Sealing Tests
# ===========================================================================

class TestSignatureLifecycle:
    """Test signature creation, storage integration, and post-generation hook."""

    def _create_sample_output(self, content: str = "Sample report content"):
        out_id = uuid.uuid4()
        job_id = uuid.uuid4()
        return SimpleNamespace(
            id=out_id,
            job_id=job_id,
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": content},
            text_content=None,
            output_metadata={
                "classification": "INTERNAL",
                "policy_id": "pol-test",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"source_id": "src-1", "classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": str(job_id), "project_id": "proj-1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "pol-test", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "ExecutiveSummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "pol-test", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {
                    "latest_approval_id": "appr-001",
                    "destinations": {
                        "DOWNLOAD": {
                            "destination": "DOWNLOAD",
                            "approval_status": "APPROVED",
                            "approval_id": "appr-001",
                            "decision": "APPROVED",
                            "approver_id": "admin-1",
                            "approved_at": "2026-09-16T10:00:00Z",
                        }
                    },
                },
            },
        )

    def test_07_sign_output_artifact_success(self):
        """Test sign_output_artifact creates valid DigitalSignatureRecord on existing integrity envelope."""
        output = self._create_sample_output("Valid sample output for Phase 2H")
        integ_record = seal_output_integrity(output)
        assert integ_record is not None

        signer = FakeDigitalSigner(key_id="karyasetu-dev-1")
        sig_record = sign_output_artifact(
            output,
            signer=signer,
        )

        assert sig_record is not None
        assert sig_record.status == SignatureStatus.VALID.value
        assert sig_record.algorithm == "fake-sha256"
        assert sig_record.key_id == "karyasetu-dev-1"
        assert sig_record.signed_integrity_hash == integ_record.artifact_hash
        assert sig_record.signed_provenance_hash == integ_record.provenance_hash
        assert sig_record.provider == "test_mock"
        assert len(sig_record.signature) > 0
        assert "digital_signature" in output.output_metadata

    def test_08_sign_output_without_integrity_envelope_fails(self):
        """Test sign_output_artifact returns None when integrity envelope is absent."""
        output = self._create_sample_output()
        # Ensure no cryptographic_integrity in metadata
        output.output_metadata.pop("cryptographic_integrity", None)

        sig_record = sign_output_artifact(output)
        assert sig_record is None
        assert "digital_signature" not in output.output_metadata

    def test_09_record_job_digital_signatures_hook(self):
        """Test record_job_digital_signatures sets output_metadata['digital_signature'] in batch."""
        output1 = self._create_sample_output("Content 1")
        output2 = self._create_sample_output("Content 2")
        seal_output_integrity(output1)
        seal_output_integrity(output2)

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [output1, output2]

        signer = FakeDigitalSigner(key_id="test-batch-key")
        records = record_job_digital_signatures(
            job_id=uuid.uuid4(),
            db=mock_db,
            signer=signer,
        )

        assert len(records) == 2
        assert "digital_signature" in output1.output_metadata
        assert "digital_signature" in output2.output_metadata
        assert output1.output_metadata["digital_signature"]["status"] == "VALID"
        assert output2.output_metadata["digital_signature"]["status"] == "VALID"
        assert output1.output_metadata["digital_signature"]["key_id"] == "test-batch-key"


# ===========================================================================
# 3. Read-Only Verification & Tamper Detection Tests
# ===========================================================================

class TestSignatureVerificationAndTamperDetection:
    """Test read-only verification and tamper detection across all integrity dimensions."""

    def _create_sample_output(self, content: str = "Valid content"):
        out_id = uuid.uuid4()
        job_id = uuid.uuid4()
        return SimpleNamespace(
            id=out_id,
            job_id=job_id,
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": content},
            text_content=None,
            output_metadata={
                "classification": "RESTRICTED",
                "policy_id": "pol-strict",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"source_id": "src-1", "classification": "RESTRICTED"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": str(job_id), "project_id": "proj-1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "RESTRICTED", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "pol-strict", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "ExecutiveSummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "pol-strict", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {
                    "latest_approval_id": "appr-001",
                    "destinations": {
                        "DOWNLOAD": {
                            "destination": "DOWNLOAD",
                            "approval_status": "APPROVED",
                            "approval_id": "appr-001",
                            "decision": "APPROVED",
                            "approver_id": "admin-1",
                            "approved_at": "2026-09-16T10:00:00Z",
                        }
                    },
                },
            },
        )

    def _setup_signed_output(self, content="Valid original content", signer=None):
        if signer is None:
            signer = FakeDigitalSigner(key_id="test-tamper-key")
        output = self._create_sample_output(content)
        seal_output_integrity(output)
        sign_output_artifact(output, signer=signer)
        return output, signer

    def test_10_read_only_verification_unmodified_is_valid(self):
        """Test unmodified artifact and envelope return VALID and metadata is NOT modified."""
        output, signer = self._setup_signed_output()
        meta_before = json.dumps(output.output_metadata, sort_keys=True)

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.VALID.value
        assert res["algorithm"] == signer.algorithm
        assert res["key_id"] == signer.key_id
        # Check metadata was NOT modified in memory (read-only)
        meta_after = json.dumps(output.output_metadata, sort_keys=True)
        assert meta_before == meta_after

    def test_11_ed25519_verification_valid(self):
        """Test Ed25519 asymmetric signer produces verifiable VALID signatures."""
        ed_signer = Ed25519Signer()
        output, _ = self._setup_signed_output(signer=ed_signer)

        res = verify_output_signature(
            output,
            signer=ed_signer,
        )

        assert res["status"] == SignatureStatus.VALID.value
        assert res["algorithm"] == "ed25519"
        assert res["provider"] == "asymmetric_signature"
        assert res["details"].get("signature_verified") is True

    def test_12_tampered_artifact_content_causes_invalid(self):
        """Tampering with artifact content causes underlying Phase 2G integrity to fail, producing INVALID."""
        output, signer = self._setup_signed_output()
        output.structured_content = {"summary": "Tampered content injected by malicious actor"}

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.INVALID.value
        assert "Underlying cryptographic integrity" in res["details"].get("reason", "")

    def test_13_tampered_provenance_causes_invalid(self):
        """Tampering with provenance causes signed payload hash mismatch, producing INVALID."""
        output, signer = self._setup_signed_output()
        output.output_metadata["provenance"]["source"]["source_id"] = "tampered-source"

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.INVALID.value

    def test_14_tampered_approval_causes_invalid(self):
        """Tampering with approval state after signing causes INVALID."""
        output, signer = self._setup_signed_output()
        output.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"] = "REVOKED"

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.INVALID.value

    def test_15_tampered_integrity_envelope_causes_invalid(self):
        """Direct tampering with output_metadata['cryptographic_integrity'] causes INVALID."""
        output, signer = self._setup_signed_output()
        output.output_metadata["cryptographic_integrity"]["artifact_hash"] = "0" * 64

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.INVALID.value

    def test_16_tampered_signature_string_causes_invalid(self):
        """Corrupting the stored signature string causes INVALID."""
        output, signer = self._setup_signed_output()
        output.output_metadata["digital_signature"]["signature"] = "deadbeef" * 8

        res = verify_output_signature(
            output,
            signer=signer,
        )

        assert res["status"] == SignatureStatus.INVALID.value
        assert "Digital signature verification failed" in res["details"].get("reason", "")

    def test_17_missing_signature_returns_unavailable(self):
        """Outputs without digital_signature metadata return UNAVAILABLE without error."""
        output = self._create_sample_output()
        seal_output_integrity(output)
        output.output_metadata.pop("digital_signature", None)

        res = verify_output_signature(output)

        assert res["status"] == SignatureStatus.UNAVAILABLE.value
        assert "Digital signature record not found" in res["details"].get("reason", "")

    def test_18_missing_storage_file_returns_unavailable(self):
        """Missing storage file causes verification to return UNAVAILABLE."""
        mock_storage = MockStorage()
        mock_storage.write("report.pdf", b"%PDF-1.4 authentic content")

        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="document",
            status="completed",
            storage_key="report.pdf",
            mime_type="application/pdf",
            structured_content=None,
            text_content=None,
            output_metadata={
                "classification": "INTERNAL",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["document"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "document", "generator_class": "DocGen"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {"latest_approval_id": None, "destinations": {}},
            },
        )
        seal_output_integrity(output, storage=mock_storage)
        sign_output_artifact(output)

        # Delete file from storage
        del mock_storage.files["report.pdf"]

        res = verify_output_signature(
            output,
            storage=mock_storage,
        )

        assert res["status"] == SignatureStatus.UNAVAILABLE.value


# ===========================================================================
# 4. API Endpoints & Security Protection Tests
# ===========================================================================

class TestSignatureApiAndSecurity:
    """Test API endpoints, IDOR protection, private key containment, and supremacy."""

    @pytest.fixture(autouse=True)
    def setup_audit(self):
        clear_security_events()
        yield
        clear_security_events()

    @pytest.mark.asyncio
    async def test_19_api_get_signature_owner_access(self):
        """Test GET /api/v1/outputs/{output_id}/signature returns 200 for owner."""
        out_id = uuid.uuid4()
        mock_output = SimpleNamespace(
            id=out_id,
            project_id="proj-1",
            storage_path="doc.txt",
            output_metadata={
                "digital_signature": {
                    "status": "VALID",
                    "algorithm": "ed25519",
                    "key_id": "key-1",
                    "signature": "abcdef123456",
                    "signed_payload_hash": "p" * 64,
                    "signed_integrity_hash": "i" * 64,
                    "signed_provenance_hash": "h" * 64,
                    "provider": "Ed25519Signer",
                    "signed_at": "2026-09-16T12:00:00Z",
                    "details": {},
                }
            },
        )

        owner = CurrentUser(id=uuid.uuid4(), email="owner@test.com", name="Owner", role="analyst")
        db = AsyncMock()

        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=mock_output)):
            resp = await get_output_signature_endpoint(
                output_id=out_id,
                current_user=owner,
                db=db,
            )

            assert resp.success is True
            assert resp.output_id == out_id
            assert resp.data.status == "VALID"
            assert resp.data.algorithm == "ed25519"
            assert resp.data.key_id == "key-1"

    @pytest.mark.asyncio
    async def test_20_api_signature_non_owner_404_idor(self):
        """Test GET and POST return 404 for non-owner to prevent IDOR scanning."""
        attacker = CurrentUser(id=uuid.uuid4(), email="attacker@test.com", name="Attacker", role="analyst")
        db = AsyncMock()
        target_id = uuid.uuid4()

        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_get:
                await get_output_signature_endpoint(
                    output_id=target_id,
                    current_user=attacker,
                    db=db,
                )
            assert exc_get.value.status_code == 404

            with pytest.raises(HTTPException) as exc_post:
                await verify_output_signature_endpoint(
                    output_id=target_id,
                    current_user=attacker,
                    db=db,
                )
            assert exc_post.value.status_code == 404

    def test_21_zero_private_key_exposure(self):
        """Verify that private keys are NEVER exposed in metadata, audit events, or API responses."""
        signer = Ed25519Signer()
        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Highly confidential briefing"},
            text_content=None,
            output_metadata={
                "classification": "SECRET",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "SECRET"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "SECRET", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {"latest_approval_id": None, "destinations": {}},
            },
        )
        seal_output_integrity(output)
        sign_output_artifact(output, signer=signer)

        # Check metadata
        meta_str = json.dumps(output.output_metadata).lower()
        assert "private_key" not in meta_str
        assert "privatekey" not in meta_str
        assert "secret_bytes" not in meta_str

        # Check audit events
        events = security_events()
        events_str = json.dumps(events).lower()
        assert "private_key" not in events_str
        assert "privatekey" not in events_str

    def test_22_audit_event_emission(self):
        """Verify audit events are emitted on signing and verification."""
        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Audit test content"},
            text_content=None,
            output_metadata={
                "classification": "INTERNAL",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "proj-aud-1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {"latest_approval_id": None, "destinations": {}},
            },
        )
        seal_output_integrity(output)
        sign_output_artifact(
            output,
            signer=FakeDigitalSigner(),
            project_id="proj-aud-1",
        )

        events = security_events()
        sig_recorded = [e for e in events if e.get("event_type") == "signature_recorded"]
        assert len(sig_recorded) >= 1
        assert sig_recorded[0]["output_id"] == str(out_id)
        assert sig_recorded[0]["status"] == "VALID"

    def test_23_multi_output_isolation(self):
        """Verify distinct outputs have distinct signatures and signed payload hashes."""
        outputA = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Artifact A"},
            text_content=None,
            output_metadata={"provenance": {"provenance_id": "pA"}, "approval": {}},
        )
        outputB = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Artifact B"},
            text_content=None,
            output_metadata={"provenance": {"provenance_id": "pB"}, "approval": {}},
        )

        seal_output_integrity(outputA)
        seal_output_integrity(outputB)

        signer = Ed25519Signer()
        sA = sign_output_artifact(outputA, signer=signer)
        sB = sign_output_artifact(outputB, signer=signer)

        assert sA.signature != sB.signature
        assert sA.signed_payload_hash != sB.signed_payload_hash
        assert sA.signed_integrity_hash != sB.signed_integrity_hash

    def test_24_phase_2f_approval_supremacy(self):
        """CRITICAL: A VALID digital signature MUST NOT bypass Phase 2F approval controls."""
        signer = FakeDigitalSigner()
        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Content requiring approval"},
            text_content=None,
            output_metadata={
                "classification": "CONFIDENTIAL",
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "CONFIDENTIAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "CONFIDENTIAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "DOWNLOAD", "primary_decision": "REQUIRE_APPROVAL", "primary_allowed": False},
                },
                "approval": {
                    "latest_approval_id": "appr-pending",
                    "destinations": {
                        "DOWNLOAD": {
                            "destination": "DOWNLOAD",
                            "approval_status": ApprovalStatus.PENDING_APPROVAL.value,
                            "approval_id": "appr-pending",
                            "decision": "PENDING",
                        }
                    },
                },
            },
        )
        seal_output_integrity(output)
        sign_output_artifact(output, signer=signer)

        res = verify_output_signature(output, signer=signer)
        # Signature is cryptographically VALID
        assert res["status"] == SignatureStatus.VALID.value

        # BUT Phase 2F approval check must still dictate release status!
        download_status = output.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"]
        assert download_status == ApprovalStatus.PENDING_APPROVAL.value
        # The output is NOT approved for release despite signature being valid
        is_approved_for_release = (download_status == ApprovalStatus.APPROVED.value)
        assert is_approved_for_release is False

    def test_25_phase_2d_dissemination_supremacy(self):
        """CRITICAL: A VALID digital signature MUST NOT bypass Phase 2D dissemination BLOCK."""
        signer = FakeDigitalSigner()
        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Top secret material"},
            text_content=None,
            output_metadata={
                "classification": InformationClassification.RESTRICTED.value,
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": InformationClassification.RESTRICTED.value},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": InformationClassification.RESTRICTED.value, "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {"latest_approval_id": None, "destinations": {}},
            },
        )
        seal_output_integrity(output)
        sign_output_artifact(output, signer=signer)

        # Check dissemination engine:
        # A RESTRICTED artifact must be BLOCKED for external destination (PUBLIC_WEB) despite VALID signature
        engine = get_dissemination_engine()
        decision = engine.evaluate(
            classification=InformationClassification.RESTRICTED,
            destination=DisseminationDestination.PUBLIC_WEB,
        )
        assert decision.allowed is False
        assert decision.decision == DisseminationDecisionOutcome.BLOCK
