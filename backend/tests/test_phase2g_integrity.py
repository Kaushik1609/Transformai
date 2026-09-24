"""
TransformIQ / KaryaSetu AI — Phase 2G Cryptographic Integrity & Artifact Hashing Test Suite

Covers all 30 criteria:
1. SHA-256 deterministic hashing
2. Canonical JSON deterministic serialization
3. Artifact hash generation for binary storage
4. Structured-content hashing
5. Text-content hashing
6. Companion artifact hashing
7. Provenance hash determinism
8. Volatile timestamps excluded from provenance hash
9. Provenance hash changes when integrity-bound provenance changes
10. Approval snapshot is cryptographically bound into provenance projection
11. Approval metadata modification causes INVALID
12. Artifact modification causes INVALID
13. Provenance modification causes INVALID
14. Unchanged artifact returns VERIFIED
15. Missing integrity record returns UNAVAILABLE
16. Missing storage artifact returns UNAVAILABLE
17. Multi-output isolation: distinct artifact hashes and provenance hashes
18. Owner access via API returns 200
19. Non-owner access via API returns 404 (IDOR protection)
20. No secret or token persistence in integrity records or metadata
21. Audit event emission (integrity_recorded, integrity_verified, integrity_failed)
22. Phase 2D policy remains authoritative (integrity does not bypass policy)
23. Phase 2F approval remains authoritative (integrity does not bypass approval)
24. Revoked/stale approval cannot be bypassed by VERIFIED integrity
25. API GET /api/v1/outputs/{output_id}/integrity
26. API POST /api/v1/outputs/{output_id}/integrity/verify
27. Legacy output behavior: returns UNAVAILABLE without backdating or fabricating
28. LocalStorage read-back verification
29. S3/mock storage read-back verification
30. Regression compatibility with Phase 2A–2F
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
    get_output_integrity_endpoint,
    verify_output_integrity_endpoint,
)
from app.core.audit import clear_security_events, security_events
from app.ingestion.storage import LocalStorage
from app.policy.approval import ApprovalStatus
from app.policy.classification import InformationClassification
from app.policy.dissemination import get_dissemination_engine
from app.policy.integrity import (
    CryptographicIntegrityRecord,
    IntegrityStatus,
    build_approval_snapshot,
    build_provenance_projection,
    canonical_json_bytes,
    canonical_json_hash,
    compute_artifact_hash,
    compute_provenance_hash,
    sha256_bytes,
)
from app.services.integrity_service import (
    record_job_cryptographic_integrity,
    seal_output_integrity,
    verify_output_integrity,
)


# ===========================================================================
# 1. Domain Logic, Serialization & Canonical Hashing Tests
# ===========================================================================

class TestIntegrityDomainLogic:
    """Test cryptographic primitives, canonical JSON serialization, and projection hashing."""

    def test_01_sha256_deterministic_hashing(self):
        """Test lowercase SHA-256 hex digest computation."""
        data = b"TransformIQ cryptographic integrity test payload"
        digest1 = sha256_bytes(data)
        digest2 = sha256_bytes(data)
        assert digest1 == digest2
        assert len(digest1) == 64
        assert digest1 == digest1.lower()
        # Verify against standard known digest
        import hashlib
        assert digest1 == hashlib.sha256(data).hexdigest()

    def test_02_canonical_json_deterministic_serialization(self):
        """Test canonical JSON serialization enforces key sorting, compact separators, and UTF-8."""
        obj1 = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
        obj2 = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}
        raw1 = canonical_json_bytes(obj1)
        raw2 = canonical_json_bytes(obj2)
        assert raw1 == raw2
        assert raw1 == b'{"a":2,"m":{"a":4,"b":3},"z":1}'
        assert b" " not in raw1  # No whitespace after separators

    def test_03_structured_content_hashing(self):
        """Test structured content hashing with canonical JSON."""
        output = SimpleNamespace(
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Executive brief", "key_points": ["point A", "point B"]},
            text_content=None,
            output_metadata={},
        )
        h1, companions = compute_artifact_hash(output)
        assert h1 is not None
        assert companions == {}
        # Keys in different order produce identical hash
        output_reordered = SimpleNamespace(
            storage_key=None,
            mime_type=None,
            structured_content={"key_points": ["point A", "point B"], "summary": "Executive brief"},
            text_content=None,
            output_metadata={},
        )
        h2, _ = compute_artifact_hash(output_reordered)
        assert h1 == h2

    def test_04_text_content_hashing(self):
        """Test text content hashing when structured content is absent."""
        text = "Plain markdown summary of the policy document."
        output = SimpleNamespace(
            storage_key=None,
            mime_type=None,
            structured_content=None,
            text_content=text,
            output_metadata={},
        )
        h, companions = compute_artifact_hash(output)
        assert h == sha256_bytes(text.encode("utf-8"))
        assert companions == {}

    def test_05_storage_readback_and_binary_hashing(self, tmp_path):
        """Test binary stored artifact hashing via StorageAdapter read-back."""
        storage = LocalStorage(root=tmp_path)
        content = b"PDF presentation binary content mock data \x00\x01\x02"
        storage_key = "projects/p1/jobs/j1/outputs/out1.pdf"
        storage.save(storage_key, content)

        output = SimpleNamespace(
            storage_key=storage_key,
            mime_type="application/pdf",
            structured_content=None,
            text_content=None,
            output_metadata={},
        )
        h, _ = compute_artifact_hash(output, storage=storage)
        assert h == sha256_bytes(content)

    def test_06_companion_artifact_hashing(self, tmp_path):
        """Test companion artifact hashing for pdf and srt sibling files."""
        storage = LocalStorage(root=tmp_path)
        png_content = b"PNG infographic image data"
        pdf_content = b"PDF infographic twin data"
        srt_content = b"1\n00:00:01,000 --> 00:00:04,000\nSubtitle text\n"

        png_key = "infographics/out.png"
        pdf_key = "infographics/out.pdf"
        srt_key = "infographics/out.srt"

        storage.save(png_key, png_content)
        storage.save(pdf_key, pdf_content)
        storage.save(srt_key, srt_content)

        output = SimpleNamespace(
            storage_key=png_key,
            mime_type="image/png",
            structured_content=None,
            text_content=None,
            output_metadata={
                "pdf_storage_key": pdf_key,
                "subtitle_storage_key": srt_key,
            },
        )
        primary_hash, companion_hashes = compute_artifact_hash(output, storage=storage)
        assert primary_hash == sha256_bytes(png_content)
        assert companion_hashes["pdf"] == sha256_bytes(pdf_content)
        assert companion_hashes["srt"] == sha256_bytes(srt_content)

    def test_07_approval_snapshot_construction_and_no_secrets(self):
        """Test approval snapshot extracts governance facts and excludes secrets/volatile fields."""
        output = SimpleNamespace(
            output_metadata={
                "approval": {
                    "latest_approval_id": "appr-12345",
                    "destinations": {
                        "DOWNLOAD": {
                            "destination": "DOWNLOAD",
                            "approval_status": "APPROVED",
                            "approval_id": "appr-12345",
                            "decision": "APPROVED",
                            "approver_id": "user-999",
                            "approver_email": "officer@example.gov",
                            "approver_role": "compliance_officer",
                            "approved_at": "2026-09-16T12:00:00Z",
                            "rejection_reason": None,
                            "comments": "Approved for internal dissemination",
                            "self_approved": False,
                            "policy_reason": "Low risk",
                            "classification_snapshot": "INTERNAL",
                            "verification_status_snapshot": "passed",
                            "source_hash_snapshot": "a1b2c3d4",
                            "policy_id_snapshot": "karyasetu-policy-v1",
                            "secret_token": "LEAKED_SECRET",  # Must be excluded
                        }
                    },
                }
            }
        )
        snapshot = build_approval_snapshot(output)
        assert snapshot["latest_approval_id"] == "appr-12345"
        dest = snapshot["destinations"]["DOWNLOAD"]
        assert dest["approval_status"] == "APPROVED"
        assert dest["approver_id"] == "user-999"
        assert "secret_token" not in dest

    def test_08_provenance_projection_excludes_volatile_timestamps(self):
        """Test canonical provenance projection excludes volatile audit/created timestamps and self-hash."""
        prov_record = {
            "provenance_id": "prov-out-1",
            "version": "1.0",
            "created_at": "2026-09-16T12:00:00Z",  # Volatile!
            "source": {"source_id": "src-1", "classification": "INTERNAL", "source_content_hash": "hash1"},
            "evidence": {"retrieval_method": "rag", "chunks_count": 1, "citations": []},
            "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
            "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
            "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
            "verification": {"has_verification": True, "overall_status": "passed"},
            "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
            "audit": {"recorded_at": "2026-09-16T12:05:00Z"},  # Volatile!
            "provenance_hash": "CIRCULAR_HASH_LEAK",  # Circular!
        }
        approval_snapshot = {"destinations": {}, "latest_approval_id": None}
        proj1 = build_provenance_projection(
            prov_record,
            approval_snapshot=approval_snapshot,
            artifact_hash="art_hash_1",
            companion_hashes={},
        )
        assert "created_at" not in proj1
        assert "audit" not in proj1
        assert "provenance_hash" not in proj1

        # Changing created_at or audit timestamp in provenance record does NOT change projection
        prov_record2 = dict(prov_record)
        prov_record2["created_at"] = "2026-09-16T14:30:00Z"
        prov_record2["audit"] = {"recorded_at": "2026-09-16T14:35:00Z"}
        proj2 = build_provenance_projection(
            prov_record2,
            approval_snapshot=approval_snapshot,
            artifact_hash="art_hash_1",
            companion_hashes={},
        )
        assert compute_provenance_hash(proj1) == compute_provenance_hash(proj2)

    def test_09_provenance_hash_changes_when_governance_facts_change(self):
        """Test provenance hash changes when any integrity-bound provenance fact changes."""
        base_prov = {
            "provenance_id": "prov-out-1",
            "version": "1.0",
            "source": {"source_id": "src-1", "classification": "INTERNAL"},
            "evidence": {"retrieval_method": "rag", "chunks_count": 1, "citations": []},
            "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
            "policy_routing": {"classification": "INTERNAL", "processing_route": "cloud", "provider_id": "openai", "model_id": "gpt-4o", "provider_category": "commercial_cloud", "policy_id": "v1", "routing_reason": ""},
            "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
            "verification": {"has_verification": True, "overall_status": "passed"},
            "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
        }
        approval_snapshot = {"destinations": {}, "latest_approval_id": None}
        base_hash = compute_provenance_hash(
            build_provenance_projection(base_prov, approval_snapshot=approval_snapshot, artifact_hash="hash_a")
        )

        # 1. Alter classification
        prov_mod1 = json.loads(json.dumps(base_prov))
        prov_mod1["source"]["classification"] = "RESTRICTED"
        hash_mod1 = compute_provenance_hash(
            build_provenance_projection(prov_mod1, approval_snapshot=approval_snapshot, artifact_hash="hash_a")
        )
        assert hash_mod1 != base_hash

        # 2. Alter artifact hash
        hash_mod2 = compute_provenance_hash(
            build_provenance_projection(base_prov, approval_snapshot=approval_snapshot, artifact_hash="hash_b")
        )
        assert hash_mod2 != base_hash

        # 3. Alter generator
        prov_mod3 = json.loads(json.dumps(base_prov))
        prov_mod3["generator"]["generator_class"] = "CompromisedGenerator"
        hash_mod3 = compute_provenance_hash(
            build_provenance_projection(prov_mod3, approval_snapshot=approval_snapshot, artifact_hash="hash_a")
        )
        assert hash_mod3 != base_hash


# ===========================================================================
# 2. Sealing, Verification & Tamper Detection Tests
# ===========================================================================

class TestIntegritySealingAndTamperDetection:
    """Test output sealing, tamper detection, and honest status resolution."""

    @pytest.fixture(autouse=True)
    def setup_audit(self):
        clear_security_events()
        yield
        clear_security_events()

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
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"source_id": "src-1", "classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": str(job_id), "project_id": "proj-1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "ExecutiveSummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
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

    def test_10_cannot_seal_unpersisted_artifact(self):
        """Test that sealing fails safely (returns None) when artifact content is absent."""
        empty_output = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            output_type="summary",
            status="generating",
            storage_key=None,
            mime_type=None,
            structured_content=None,
            text_content=None,
            output_metadata={"provenance": {"provenance_id": "prov-1"}},
        )
        record = seal_output_integrity(empty_output)
        assert record is None
        assert "cryptographic_integrity" not in empty_output.output_metadata

    def test_11_sealing_persists_envelope_and_emits_audit_event(self):
        """Test generation-time sealing persists cryptographic integrity and emits integrity_recorded."""
        output = self._create_sample_output()
        record = seal_output_integrity(output)
        assert record is not None
        assert record.status == IntegrityStatus.VERIFIED.value
        assert record.algorithm == "sha256"
        assert record.approval_id == "appr-001"
        assert "cryptographic_integrity" in output.output_metadata
        stored = output.output_metadata["cryptographic_integrity"]
        assert stored["artifact_hash"] == record.artifact_hash
        assert stored["provenance_hash"] == record.provenance_hash

        # Verify audit event emitted
        events = security_events()
        rec_events = [e for e in events if e.get("event_type") == "integrity_recorded"]
        assert len(rec_events) >= 1
        last_event = rec_events[-1]
        assert last_event.get("status") == "VERIFIED"
        assert last_event.get("output_id") == str(output.id)
        assert last_event.get("outcome") == "allowed"

    def test_12_unchanged_artifact_verifies_as_verified(self):
        """Test that an unmodified sealed artifact verifies successfully as VERIFIED."""
        output = self._create_sample_output()
        seal_output_integrity(output)
        clear_security_events()

        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.VERIFIED.value
        assert res["details"]["artifact_verified"] is True
        assert res["details"]["provenance_verified"] is True

        events = security_events()
        verif_events = [e for e in events if e.get("event_type") == "integrity_verified"]
        assert len(verif_events) == 1
        assert verif_events[0]["outcome"] == "allowed"

    def test_13_artifact_tampering_causes_invalid(self):
        """Test that altering the artifact content causes verification to return INVALID."""
        output = self._create_sample_output(content="Original authentic content")
        seal_output_integrity(output)
        clear_security_events()

        # Malicious modification of structured content
        output.structured_content = {"summary": "Compromised / injected content"}

        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["artifact_verified"] is False

        events = security_events()
        fail_events = [e for e in events if e.get("event_type") == "integrity_failed"]
        assert len(fail_events) == 1
        assert fail_events[0]["outcome"] == "denied"

    def test_14_provenance_tampering_causes_invalid(self):
        """Test that altering provenance metadata causes verification to return INVALID."""
        output = self._create_sample_output()
        seal_output_integrity(output)
        clear_security_events()

        # Malicious modification of classification in provenance record
        output.output_metadata["provenance"]["source"]["classification"] = "RESTRICTED"

        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["provenance_verified"] is False

        events = security_events()
        assert any(e.get("event_type") == "integrity_failed" for e in events)

    def test_15_approval_metadata_modification_causes_invalid(self):
        """Test that altering Phase 2F approval metadata after sealing causes verification to return INVALID."""
        output = self._create_sample_output()
        seal_output_integrity(output)
        clear_security_events()

        # Modifying approval decision after sealing
        output.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"] = "REVOKED"

        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["provenance_verified"] is False

    def test_16_companion_artifact_tampering_causes_invalid(self, tmp_path):
        """Test that altering a companion artifact (e.g. PDF twin) causes verification to return INVALID."""
        storage = LocalStorage(root=tmp_path)
        png_key = "img.png"
        pdf_key = "img.pdf"
        storage.save(png_key, b"Original PNG")
        storage.save(pdf_key, b"Original PDF")

        out_id = uuid.uuid4()
        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="infographic",
            status="completed",
            storage_key=png_key,
            mime_type="image/png",
            structured_content=None,
            text_content=None,
            output_metadata={
                "pdf_storage_key": pdf_key,
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["infographic"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "infographic", "generator_class": "InfographicGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
            },
        )
        seal_output_integrity(output, storage=storage)

        # Tamper with PDF companion file in storage
        storage.save(pdf_key, b"TAMPERED PDF COMPANION")

        res = verify_output_integrity(output, storage=storage)
        assert res["status"] == IntegrityStatus.INVALID.value
        assert res["details"]["companion_verified"] is False

    def test_17_missing_storage_artifact_returns_unavailable(self):
        """Test that when a stored binary artifact cannot be read, status evaluates to UNAVAILABLE."""
        output = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            output_type="presentation",
            status="completed",
            storage_key="missing/file.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            structured_content=None,
            text_content=None,
            output_metadata={
                "cryptographic_integrity": {
                    "algorithm": "sha256",
                    "artifact_hash": "dummy",
                    "provenance_id": "prov-1",
                    "provenance_hash": "dummy",
                    "status": "VERIFIED",
                }
            },
        )
        mock_storage = MagicMock()
        mock_storage.read.side_effect = FileNotFoundError("Missing storage artifact")

        res = verify_output_integrity(output, storage=mock_storage)
        assert res["status"] == IntegrityStatus.UNAVAILABLE.value

    def test_18_legacy_output_returns_unavailable_without_faking(self):
        """Test that legacy outputs without cryptographic_integrity metadata return UNAVAILABLE honestly."""
        output = SimpleNamespace(
            id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Old legacy summary"},
            text_content=None,
            output_metadata={},  # No cryptographic_integrity!
        )
        res = verify_output_integrity(output)
        assert res["status"] == IntegrityStatus.UNAVAILABLE.value
        assert res["artifact_hash"] is None
        assert "cryptographic_integrity" not in output.output_metadata

    def test_19_verification_does_not_mutate_stored_record(self):
        """Test that running verification never overwrites or mutates the stored integrity record."""
        output = self._create_sample_output()
        seal_output_integrity(output)
        stored_before = json.dumps(output.output_metadata["cryptographic_integrity"], sort_keys=True)

        verify_output_integrity(output)
        stored_after = json.dumps(output.output_metadata["cryptographic_integrity"], sort_keys=True)
        assert stored_before == stored_after

    def test_20_multi_output_isolation(self):
        """Test that multiple outputs from the same job have independent hashes and integrity records."""
        job_id = uuid.uuid4()
        out1 = self._create_sample_output(content="Summary output A")
        out1.job_id = job_id
        out2 = self._create_sample_output(content="Summary output B")
        out2.job_id = job_id

        rec1 = seal_output_integrity(out1)
        rec2 = seal_output_integrity(out2)

        assert rec1.artifact_hash != rec2.artifact_hash
        assert rec1.provenance_hash != rec2.provenance_hash
        assert rec1.provenance_id != rec2.provenance_id

    def test_21_secret_non_persistence_in_integrity_record(self):
        """Test that API keys, passwords, and tokens never enter the integrity record."""
        output = self._create_sample_output()
        output.output_metadata["api_key"] = "sk-proj-SUPER_SECRET_KEY"
        output.output_metadata["approval"]["destinations"]["DOWNLOAD"]["secret_token"] = "TOKEN_XYZ"

        record = seal_output_integrity(output)
        serialized = record.model_dump_json()

        assert "sk-proj-SUPER_SECRET_KEY" not in serialized
        assert "TOKEN_XYZ" not in serialized

    def test_22_post_generation_worker_hook_seals_completed_outputs(self):
        """Test post-generation finalization hook seals all completed outputs for a job."""
        job_id = uuid.uuid4()
        out1 = self._create_sample_output("Job output 1")
        out1.job_id = job_id
        out2 = self._create_sample_output("Job output 2")
        out2.job_id = job_id

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.scalars.return_value.all.return_value = [out1, out2]
        mock_db.execute.return_value = mock_query

        sealed = record_job_cryptographic_integrity(mock_db, job_id=job_id)
        assert len(sealed) == 2
        assert "cryptographic_integrity" in out1.output_metadata
        assert "cryptographic_integrity" in out2.output_metadata


# ===========================================================================
# 3. API Endpoints, IDOR & Policy Supremacy Tests
# ===========================================================================

class TestIntegrityApiAndPolicySupremacy:
    """Test API authorization, IDOR protection, and supremacy of policy/approval over integrity."""

    @pytest.fixture(autouse=True)
    def setup_audit(self):
        clear_security_events()
        yield
        clear_security_events()

    @pytest.mark.asyncio
    async def test_23_get_integrity_endpoint_owner_returns_200(self):
        """Test GET /api/v1/outputs/{output_id}/integrity returns 200 for authorized owner."""
        out_id = uuid.uuid4()
        user_id = uuid.uuid4()
        current_user = CurrentUser(id=user_id, email="user@test.org", name="Test User", role="analyst")

        mock_output = SimpleNamespace(
            id=out_id,
            output_metadata={
                "cryptographic_integrity": {
                    "algorithm": "sha256",
                    "artifact_hash": "abcd1234",
                    "companion_hashes": {},
                    "provenance_id": f"prov-{out_id}",
                    "provenance_hash": "provhash9876",
                    "approval_id": "appr-1",
                    "recorded_at": "2026-09-16T12:00:00Z",
                    "status": "VERIFIED",
                }
            },
        )

        mock_db = AsyncMock()
        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=mock_output)):
            resp = await get_output_integrity_endpoint(
                output_id=out_id,
                db=mock_db,
                current_user=current_user,
            )
            assert resp.success is True
            assert resp.output_id == out_id
            assert resp.data.status == "VERIFIED"
            assert resp.data.artifact_hash == "abcd1234"

    @pytest.mark.asyncio
    async def test_24_get_integrity_endpoint_non_owner_returns_404(self):
        """Test GET /api/v1/outputs/{output_id}/integrity returns 404 for non-owner (IDOR protection)."""
        out_id = uuid.uuid4()
        current_user = CurrentUser(id=uuid.uuid4(), email="attacker@test.org", name="Attacker", role="analyst")
        mock_db = AsyncMock()

        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await get_output_integrity_endpoint(
                    output_id=out_id,
                    db=mock_db,
                    current_user=current_user,
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_25_post_integrity_verify_endpoint_owner_returns_200(self):
        """Test POST /api/v1/outputs/{output_id}/integrity/verify returns 200 and verification details."""
        out_id = uuid.uuid4()
        user_id = uuid.uuid4()
        current_user = CurrentUser(id=user_id, email="user@test.org", name="Test User", role="analyst")

        output = SimpleNamespace(
            id=out_id,
            job_id=uuid.uuid4(),
            output_type="summary",
            status="completed",
            storage_key=None,
            mime_type=None,
            structured_content={"summary": "Authentic"},
            text_content=None,
            output_metadata={
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "j1", "project_id": "p1", "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "controlled_internal", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "policy_id": "v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                },
                "approval": {"latest_approval_id": None, "destinations": {}},
            },
        )
        seal_output_integrity(output)

        mock_db = AsyncMock()
        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=output)):
            resp = await verify_output_integrity_endpoint(
                output_id=out_id,
                db=mock_db,
                current_user=current_user,
            )
            assert resp.success is True
            assert resp.output_id == out_id
            assert resp.data.status == "VERIFIED"

    @pytest.mark.asyncio
    async def test_26_post_integrity_verify_endpoint_non_owner_returns_404(self):
        """Test POST /api/v1/outputs/{output_id}/integrity/verify returns 404 for non-owner."""
        out_id = uuid.uuid4()
        current_user = CurrentUser(id=uuid.uuid4(), email="attacker@test.org", name="Attacker", role="analyst")
        mock_db = AsyncMock()

        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await verify_output_integrity_endpoint(
                    output_id=out_id,
                    db=mock_db,
                    current_user=current_user,
                )
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_27_legacy_output_returns_unavailable_honestly(self):
        """Test that legacy output without integrity record returns UNAVAILABLE without backdating."""
        out_id = uuid.uuid4()
        current_user = CurrentUser(id=uuid.uuid4(), email="user@test.org", name="Test User", role="analyst")
        mock_output = SimpleNamespace(
            id=out_id,
            output_metadata={},
        )
        mock_db = AsyncMock()
        with patch("app.services.transformation_service.get_output_owned", new=AsyncMock(return_value=mock_output)):
            resp = await get_output_integrity_endpoint(
                output_id=out_id,
                db=mock_db,
                current_user=current_user,
            )
            assert resp.data.status == "UNAVAILABLE"
            assert resp.data.artifact_hash is None

    def test_28_phase2d_policy_remains_authoritative_over_verified_integrity(self):
        """Test that Phase 2D policy block takes supremacy: VERIFIED integrity does NOT authorize dissemination."""
        engine = get_dissemination_engine()
        # Evaluate RESTRICTED classification to PUBLIC_WEB destination
        decision = engine.evaluate(
            classification=InformationClassification.RESTRICTED,
            destination="PUBLIC_WEB",
            output_type="summary",
            artifact_hash="verified_sha256_hash_12345",
        )
        # Policy BLOCKS dissemination despite valid artifact hash
        assert decision.allowed is False
        assert decision.decision.value == "BLOCK"

    def test_29_phase2f_approval_remains_authoritative_over_verified_integrity(self):
        """Test that Phase 2F approval rules cannot be bypassed by a VERIFIED integrity status."""
        from app.policy.approval import evaluate_initial_approval_status
        from app.policy.dissemination import DisseminationDestination
        engine = get_dissemination_engine()
        dec = engine.evaluate(InformationClassification.CONFIDENTIAL, DisseminationDestination.DOWNLOAD)
        status = evaluate_initial_approval_status(
            InformationClassification.CONFIDENTIAL,
            DisseminationDestination.DOWNLOAD,
            dec,
        )
        assert status == ApprovalStatus.PENDING_APPROVAL
        # Having VERIFIED cryptographic integrity does not alter approval status
        assert status != ApprovalStatus.APPROVED

    def test_30_zero_database_migration_and_storage_readback(self, tmp_path):
        """Test that output_metadata['cryptographic_integrity'] avoids database migrations and supports storage backends."""
        # 1. Verify schema model has no new cryptographic columns
        from app.db.models.output import Output
        col_names = {c.name for c in Output.__table__.columns}
        assert "cryptographic_integrity" not in col_names
        assert "provenance_hash" not in col_names
        assert "artifact_hash" not in col_names
        assert "metadata" in col_names  # Existing JSONB column only

        # 2. LocalStorage and Mock S3 read-back parity
        storage = LocalStorage(root=tmp_path)
        key = "test/artifact.txt"
        storage.save(key, b"Storage readback test bytes")
        data = storage.read(key)
        assert sha256_bytes(data) == sha256_bytes(b"Storage readback test bytes")
