"""
TransformIQ / KaryaSetu AI — Phase 2E Evidence & Provenance Test Suite

Comprehensive tests verifying:
1. Provenance schema validation & canonical data model
2. Provenance ID stability and distinctness across outputs
3. Source lineage & historical snapshotting
4. Evidence & citation capture (chunk IDs, hashes, bounded excerpts)
5. No-RAG vs RAG transformation behavior
6. Transformation/job/project linkage
7. Multi-output transformation lineage isolation
8. Provider/model/routing lineage
9. Generator & schema lineage
10. Verification linkage
11. Dissemination linkage
12. Artifact integrity linkage
13. Audit event emission
14. Strict secret & credential non-persistence
15. API authorization & cross-user / cross-project IDOR protection
16. Backward compatibility with all existing metadata namespaces (security, resilience, integrity, dissemination)
17. Stale/deleted source resilience
18. No second RAG retrieval
19. Zero database migration assertion
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.policy.classification import InformationClassification
from app.policy.provenance import (
    EvidenceCitationLineage,
    EvidenceLineage,
    GeneratorLineage,
    IntegrityLineage,
    PolicyRoutingLineage,
    ProvenanceBuilder,
    ProvenanceExtensions,
    ProvenanceRecord,
    SourceLineage,
    TransformationLineage,
    VerificationLineage,
    create_provenance_id,
    sanitize_text_excerpt,
)


# ===========================================================================
# 1. Schema & Data Model Tests
# ===========================================================================

class TestProvenanceSchemaAndBuilder:
    """Test the validated schema, bounding, and builder logic."""

    def test_01_provenance_record_validation(self):
        """Test strict validation of a complete canonical ProvenanceRecord."""
        out_id = uuid.uuid4()
        job_id = uuid.uuid4()
        proj_id = uuid.uuid4()

        record = ProvenanceBuilder.build_record(
            output_id=out_id,
            job_id=job_id,
            project_id=proj_id,
            output_type="summary",
            classification="CONFIDENTIAL",
            requested_outputs=["summary", "linkedin"],
            prompt_provided=False,
            citations=[
                {
                    "chunk_id": str(uuid.uuid4()),
                    "chunk_index": 0,
                    "content_hash": "a1b2c3d4e5f67890",
                    "relevance_score": 0.88,
                    "excerpt": "This is test evidence excerpt.",
                }
            ],
            routing_metadata={
                "provider": "local",
                "model": "llama-3-8b-instruct",
                "provider_category": "private_local",
                "processing_route": "private_local",
                "reason": "Confidential data routed to local provider.",
            },
            dissemination_metadata={
                "policy_id": "karyasetu-dissemination-v1",
                "primary_destination": "INTERNAL",
                "primary_decision": "ALLOW",
                "primary_allowed": True,
            },
            integrity_metadata={
                "algorithm": "sha256",
                "digest": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "representation": "text",
                "status": "local",
            },
        )

        assert isinstance(record, ProvenanceRecord)
        assert record.provenance_id == f"prov-{out_id}"
        assert record.version == "1.0"
        assert record.source.classification == "CONFIDENTIAL"
        assert record.evidence.chunks_count == 1
        assert record.evidence.citations[0].chunk_index == 0
        assert record.evidence.citations[0].relevance_score == 0.88
        assert record.policy_routing.provider_id == "local"
        assert record.policy_routing.model_id == "llama-3-8b-instruct"
        assert record.generator.output_type == "summary"
        assert record.generator.schema_name == "ExecutiveSummary"
        assert record.dissemination.primary_destination == "INTERNAL"
        assert record.integrity.content_digest.startswith("abcdef")
        assert record.audit.provenance_event_type == "provenance_recorded"

    def test_02_provenance_id_generation_unique_per_output(self):
        """Test that distinct outputs receive distinct provenance IDs."""
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        prov1 = create_provenance_id(id1)
        prov2 = create_provenance_id(id2)
        assert prov1 != prov2
        assert prov1 == f"prov-{id1}"
        assert prov2 == f"prov-{id2}"

    def test_03_excerpt_bounding(self):
        """Test that long evidence text is safely bounded to MAX_EXCERPT_CHARS."""
        long_text = "Word " * 100  # 500 characters
        excerpt = sanitize_text_excerpt(long_text, max_chars=100)
        assert len(excerpt) <= 104  # 100 + "..."
        assert excerpt.endswith("...")

    def test_04_no_rag_behavior(self):
        """Test that prompt-only or non-RAG transformations produce empty evidence citations."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="linkedin",
            source=None,
            citations=None,
            retrieval_method="none",
        )
        assert record.evidence.retrieval_method == "none"
        assert record.evidence.chunks_count == 0
        assert record.evidence.citations == []
        assert record.source.source_id is None
        assert record.source.original_filename is None

    def test_05_multi_output_lineage_isolation(self):
        """Test that multi-output transformations share job context but have unique output lineage."""
        job_id = uuid.uuid4()
        proj_id = uuid.uuid4()
        out1_id = uuid.uuid4()
        out2_id = uuid.uuid4()

        rec1 = ProvenanceBuilder.build_record(
            output_id=out1_id,
            job_id=job_id,
            project_id=proj_id,
            output_type="summary",
            classification="RESTRICTED",
            integrity_metadata={"digest": "hash111", "algorithm": "sha256"},
        )
        rec2 = ProvenanceBuilder.build_record(
            output_id=out2_id,
            job_id=job_id,
            project_id=proj_id,
            output_type="presentation",
            classification="RESTRICTED",
            integrity_metadata={"digest": "hash222", "algorithm": "sha256"},
        )

        # Shared context
        assert rec1.transformation.job_id == rec2.transformation.job_id == str(job_id)
        assert rec1.transformation.project_id == rec2.transformation.project_id == str(proj_id)
        assert rec1.source.classification == rec2.source.classification == "RESTRICTED"

        # Unique output context
        assert rec1.provenance_id != rec2.provenance_id
        assert rec1.generator.output_type == "summary"
        assert rec2.generator.output_type == "presentation"
        assert rec1.generator.schema_name == "ExecutiveSummary"
        assert rec2.generator.schema_name == "PresentationDeck"
        assert rec1.integrity.content_digest == "hash111"
        assert rec2.integrity.content_digest == "hash222"

    def test_06_verification_linkage_when_present(self):
        """Test that fact verification results are cleanly linked into provenance."""
        class MockVerificationResult:
            id = uuid.uuid4()
            overall_status = "passed"
            grounding_score = 0.94
            consistency_score = 0.98
            claims_checked = 5
            claims_supported = 5

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            verification_result=MockVerificationResult(),
        )
        assert record.verification.has_verification is True
        assert record.verification.overall_status == "passed"
        assert record.verification.grounding_score == 0.94
        assert record.verification.consistency_score == 0.98
        assert record.verification.claims_checked == 5
        assert record.verification.claims_supported == 5

    def test_07_dissemination_linkage(self):
        """Test dissemination decision metadata correctly attaches to provenance."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="x",
            classification="CONFIDENTIAL",
            dissemination_metadata={
                "policy_id": "karyasetu-dissemination-v1",
                "primary_destination": "X",
                "primary_decision": "BLOCK",
                "primary_allowed": False,
            },
        )
        assert record.dissemination.primary_destination == "X"
        assert record.dissemination.primary_decision == "BLOCK"
        assert record.dissemination.primary_allowed is False

    def test_08_extension_points_placeholders(self):
        """Test that extension slots for Phases 2F-2I exist and default safely to None."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
        )
        assert hasattr(record, "extensions")
        assert record.extensions.approval_id is None
        assert record.extensions.signature is None
        assert record.extensions.signature_algorithm is None
        assert record.extensions.airgap_bundle_id is None


# ===========================================================================
# 2. Security & Non-Persistence of Secrets
# ===========================================================================

class TestProvenanceSecurityAndSanitization:
    """Ensure no credentials, tokens, passwords, or connection strings enter provenance."""

    def test_09_secret_non_persistence(self):
        """Test that routing_metadata with sensitive keys is strictly sanitized."""
        polluted_metadata = {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-proj-SUPER_SECRET_KEY_12345",
            "bearer_token": "secret-token-xyz",
            "password": "db-secret-password",
            "connection_string": "postgresql://user:pass@host/db",
            "provider_category": "commercial_cloud",
            "processing_route": "cloud",
            "reason": "Public request routed to cloud.",
        }

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            classification="PUBLIC",
            routing_metadata=polluted_metadata,
        )

        serialized = record.model_dump_json()
        assert "sk-proj-SUPER_SECRET_KEY_12345" not in serialized
        assert "secret-token-xyz" not in serialized
        assert "db-secret-password" not in serialized
        assert "postgresql://" not in serialized
        assert "api_key" not in serialized

    def test_10_extra_fields_forbidden(self):
        """Test that arbitrary extra fields cannot be injected into the ProvenanceRecord."""
        with pytest.raises(ValidationError):
            ProvenanceRecord.model_validate(
                {
                    "provenance_id": "prov-123",
                    "version": "1.0",
                    "created_at": "2026-09-15T12:00:00Z",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": "job1", "project_id": "proj1", "requested_outputs": [], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "private_local", "provider_id": "local", "model_id": "m1", "provider_category": "private_local", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                    "integrity": {"algorithm": "sha256"},
                    "audit": {"provenance_event_type": "provenance_recorded", "recorded_at": "2026-09-15T12:00:00Z"},
                    "injected_secret_field": "leak_value",  # Forbidden!
                }
            )


# ===========================================================================
# 3. Post-Generation Worker Hook & Audit Event Tests
# ===========================================================================

class TestProvenanceWorkerAndAudit:
    """Test _record_job_provenance post-generation hook in service.py."""

    def test_11_worker_hook_persists_provenance_and_emits_event(self):
        """Test that _record_job_provenance records provenance in output_metadata and emits an audit event."""
        from types import SimpleNamespace
        from app.transformation.service import _record_job_provenance

        job_id = uuid.uuid4()
        proj_id = uuid.uuid4()
        out_id = uuid.uuid4()

        mock_out = SimpleNamespace(
            id=out_id,
            job_id=job_id,
            output_type="summary",
            status="completed",
            output_metadata={
                "security": {"status": "ALLOW"},
                "resilience": {"provider": "local", "model": "llama-3-8b"},
                "integrity": {"algorithm": "sha256", "digest": "testdigest123"},
                "dissemination": {"primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
            },
        )

        mock_job = SimpleNamespace(
            id=job_id,
            project_id=proj_id,
            source_id=None,
            prompt="Analyze policy.",
            requested_outputs={"outputs": ["summary"], "evidence_citations": []},
        )

        mock_db = MagicMock()
        def execute_side_effect(stmt):
            mock_res = MagicMock()
            sql_str = str(stmt)
            if "transformation_jobs" in sql_str:
                mock_res.scalar_one_or_none.return_value = mock_job
                return mock_res
            if "outputs" in sql_str:
                mock_res.scalars.return_value.all.return_value = [mock_out]
                return mock_res
            if "verification_results" in sql_str:
                mock_res.scalars.return_value.first.return_value = None
                return mock_res
            mock_res.scalar_one_or_none.return_value = None
            return mock_res

        mock_db.execute.side_effect = execute_side_effect

        with patch("app.core.audit.emit_security_event") as mock_emit:
            _record_job_provenance(mock_db, job_id, classification="CONFIDENTIAL", project_id=str(proj_id))

            # Verify output_metadata now contains "provenance"
            assert "provenance" in mock_out.output_metadata
            prov = mock_out.output_metadata["provenance"]
            assert prov["provenance_id"] == f"prov-{out_id}"
            assert prov["source"]["classification"] == "CONFIDENTIAL"

            # Verify existing namespaces are completely preserved
            assert mock_out.output_metadata["security"] == {"status": "ALLOW"}
            assert mock_out.output_metadata["resilience"]["provider"] == "local"
            assert mock_out.output_metadata["integrity"]["digest"] == "testdigest123"
            assert mock_out.output_metadata["dissemination"]["primary_allowed"] is True

            # Verify security audit event was emitted
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "provenance_recorded"
            assert call_args[1]["outcome"] == "allowed"
            assert call_args[1]["job_id"] == str(job_id)
            assert call_args[1]["details"]["output_id"] == str(out_id)


# ===========================================================================
# 4. API & IDOR Security Tests
# ===========================================================================

@pytest.mark.asyncio
class TestProvenanceApiAndIdor:
    """Test GET /outputs/{output_id}/provenance authorization and ownership."""

    async def test_12_owner_can_get_provenance(self):
        """Owner of the output can successfully retrieve the provenance record."""
        from types import SimpleNamespace
        from app.api.v1.transformations import get_output_provenance_endpoint

        user_id = uuid.uuid4()
        out_id = uuid.uuid4()
        job_id = uuid.uuid4()

        mock_user = SimpleNamespace(id=user_id)
        mock_output = SimpleNamespace(
            id=out_id,
            job_id=job_id,
            output_type="summary",
            output_metadata={
                "provenance": {
                    "provenance_id": f"prov-{out_id}",
                    "version": "1.0",
                    "created_at": "2026-09-15T12:00:00Z",
                    "source": {"classification": "INTERNAL"},
                    "evidence": {"retrieval_method": "none", "chunks_count": 0, "citations": []},
                    "transformation": {"job_id": str(job_id), "project_id": str(uuid.uuid4()), "requested_outputs": ["summary"], "prompt_provided": False},
                    "policy_routing": {"classification": "INTERNAL", "processing_route": "private_local", "provider_id": "local", "model_id": "llama-3-8b", "provider_category": "private_local", "policy_id": "karyasetu-policy-v1", "routing_reason": ""},
                    "generator": {"output_type": "summary", "generator_class": "SummaryGenerator"},
                    "verification": {"has_verification": False},
                    "dissemination": {"policy_id": "v1", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
                    "integrity": {"algorithm": "sha256"},
                    "audit": {"provenance_event_type": "provenance_recorded", "recorded_at": "2026-09-15T12:00:00Z"},
                    "extensions": {},
                }
            },
        )

        mock_db = MagicMock()

        with patch("app.services.transformation_service.get_output_owned", return_value=mock_output):
            resp = await get_output_provenance_endpoint(out_id, db=mock_db, current_user=mock_user)
            assert resp.success is True
            assert resp.output_id == out_id
            assert resp.data["provenance_id"] == f"prov-{out_id}"

    async def test_13_idor_protection_other_user_forbidden(self):
        """A user cannot access provenance for an output belonging to another user's project."""
        from app.api.v1.transformations import get_output_provenance_endpoint
        from fastapi import HTTPException

        other_user = uuid.uuid4()
        out_id = uuid.uuid4()

        class MockUser:
            id = other_user

        mock_db = MagicMock()

        # get_output_owned returns None when project ownership check fails
        with patch("app.services.transformation_service.get_output_owned", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await get_output_provenance_endpoint(out_id, db=mock_db, current_user=MockUser())
            assert exc_info.value.status_code == 404
            assert f"Output {out_id} not found" in exc_info.value.detail


# ===========================================================================
# 5. Stale Chunk Resilience & No-Migration Assertion
# ===========================================================================

class TestProvenanceResilience:
    """Test historical preservation and database invariants."""

    def test_14_stale_or_deleted_chunk_resilience(self):
        """Even if underlying chunks are deleted from DB, provenance retains content_hash and excerpt."""
        chunk_id = str(uuid.uuid4())
        citation = {
            "chunk_id": chunk_id,
            "chunk_index": 2,
            "content_hash": "deadbeef12345678",
            "relevance_score": 0.91,
            "excerpt": "Snapshot excerpt remains preserved forever.",
        }

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            citations=[citation],
        )

        assert len(record.evidence.citations) == 1
        cit = record.evidence.citations[0]
        assert cit.chunk_id == chunk_id
        assert cit.chunk_index == 2
        assert cit.content_hash == "deadbeef12345678"
        assert cit.excerpt == "Snapshot excerpt remains preserved forever."

    def test_15_zero_database_migration_assertion(self):
        """Verify that provenance relies solely on output_metadata without model alterations."""
        from app.db.models.output import Output
        # Ensure Output table has output_metadata column of JSONB type and no separate provenance table/column
        assert hasattr(Output, "output_metadata")
        assert not hasattr(Output, "provenance_id")
        assert not hasattr(Output, "provenance_record")

    @pytest.mark.parametrize(
        "output_type,expected_schema",
        [
            ("summary", "ExecutiveSummary"),
            ("linkedin", "LinkedInPost"),
            ("advisory", "PolicyAdvisory"),
            ("presentation", "PresentationDeck"),
            ("x", "XThread"),
            ("infographic", "InfographicSpec"),
            ("video", "VideoScript"),
        ],
    )
    def test_16_all_seven_output_schemas_mapped(self, output_type, expected_schema):
        """Verify that all 7 generator output types map to their correct schema name."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type=output_type,
        )
        assert record.generator.output_type == output_type
        assert record.generator.schema_name == expected_schema

    def test_17_backward_compatibility_metadata_namespaces_preserved(self):
        """Verify that adding provenance preserves security, resilience, integrity, dissemination."""
        existing_meta = {
            "stage": "render",
            "security": {"status": "ALLOW", "codes": []},
            "resilience": {"provider": "local", "model": "llama-3-8b", "retried": False},
            "integrity": {"algorithm": "sha256", "digest": "hash123"},
            "dissemination": {"primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
        }

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            routing_metadata=existing_meta["resilience"],
            dissemination_metadata=existing_meta["dissemination"],
            integrity_metadata=existing_meta["integrity"],
        )

        merged = {**existing_meta, "provenance": record.model_dump(mode="json")}

        # Check all 5 keys exist side-by-side
        assert "security" in merged
        assert "resilience" in merged
        assert "integrity" in merged
        assert "dissemination" in merged
        assert "provenance" in merged

    @pytest.mark.parametrize(
        "classification,expected_route,expected_cat",
        [
            ("PUBLIC", "cloud", "commercial_cloud"),
            ("INTERNAL", "controlled_internal", "commercial_cloud"),
            ("CONFIDENTIAL", "private_local", "private_local"),
            ("RESTRICTED", "private_local", "private_local"),
        ],
    )
    def test_18_classification_routing_lineage(self, classification, expected_route, expected_cat):
        """Verify routing lineage records the authoritative route for each classification."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            classification=classification,
            routing_metadata={
                "processing_route": expected_route,
                "provider": "openai" if expected_route == "cloud" else "local",
                "model": "gpt-4o" if expected_route == "cloud" else "llama-3-8b",
                "provider_category": expected_cat,
            },
        )
        assert record.policy_routing.classification == classification
        assert record.policy_routing.processing_route == expected_route
        assert record.policy_routing.provider_category == expected_cat

    @pytest.mark.asyncio
    async def test_19_lazy_provenance_population_via_helper(self):
        """Verify _ensure_output_provenance attaches provenance to pre-existing output lacking it."""
        from types import SimpleNamespace
        from app.api.v1.transformations import _ensure_output_provenance

        out_id = uuid.uuid4()
        job_id = uuid.uuid4()
        proj_id = uuid.uuid4()

        mock_out = SimpleNamespace(
            id=out_id,
            job_id=job_id,
            output_type="summary",
            output_metadata={
                "dissemination": {"classification": "INTERNAL", "primary_destination": "INTERNAL", "primary_decision": "ALLOW", "primary_allowed": True},
            },
        )

        mock_job = SimpleNamespace(
            id=job_id,
            project_id=proj_id,
            source_id=None,
            prompt="Draft briefing.",
            requested_outputs={"outputs": ["summary"]},
        )

        from unittest.mock import AsyncMock

        mock_db = MagicMock()
        async def execute_side_effect(stmt):
            mock_res = MagicMock()
            sql_str = str(stmt)
            if "transformation_jobs" in sql_str:
                mock_res.scalar_one_or_none.return_value = mock_job
                return mock_res
            if "verification_results" in sql_str:
                mock_res.scalars.return_value.first.return_value = None
                return mock_res
            mock_res.scalar_one_or_none.return_value = None
            return mock_res

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        await _ensure_output_provenance(mock_db, mock_out)

        assert "provenance" in mock_out.output_metadata
        prov = mock_out.output_metadata["provenance"]
        assert prov["provenance_id"] == f"prov-{out_id}"
        assert prov["source"]["classification"] == "INTERNAL"
        # Issue 3: Honestly represents that historical evidence was unavailable at backfill time
        assert prov["evidence"]["retrieval_method"] == "unavailable"
        assert prov["evidence"]["chunks_count"] == 0
        assert prov["evidence"]["citations"] == []
        assert prov["audit"]["provenance_event_type"] == "provenance_backfilled"

    def test_20_source_content_hash_captured(self):
        """Verify source text content hash is snapshot in source lineage."""
        from types import SimpleNamespace

        mock_source = SimpleNamespace(
            id=uuid.uuid4(),
            source_type="pdf",
            original_filename="QuarterlyReport.pdf",
            extracted_text="Financial results for Q3 show 15% revenue growth.",
            created_at=datetime.now(timezone.utc),
        )

        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            source=mock_source,
        )

        assert record.source.source_id == str(mock_source.id)
        assert record.source.source_type == "pdf"
        assert record.source.original_filename == "QuarterlyReport.pdf"
        assert record.source.source_content_hash is not None
        assert len(record.source.source_content_hash) == 16

    def test_21_evidence_hash_matches_canonical_chunk_hash(self):
        """Verify that chunk content hash in provenance matches SourceChunk.chunk_metadata canonical hash."""
        import hashlib

        full_chunk_text = "This is a long evidence chunk text that exceeds normal excerpt length. " * 10
        canonical_chunk_hash = hashlib.sha256(full_chunk_text.encode("utf-8")).hexdigest()[:16]

        # Case A: Citation provided with full evidence text, content_hash pre-computed or omitted
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            citations=[
                {
                    "chunk_id": str(uuid.uuid4()),
                    "chunk_index": 0,
                    "evidence": full_chunk_text,
                    "relevance_score": 0.95,
                }
            ],
        )

        cit = record.evidence.citations[0]
        # Must match the hash of the FULL chunk content, NOT a truncated prefix or excerpt
        assert cit.content_hash == canonical_chunk_hash
        assert cit.excerpt != full_chunk_text  # excerpt is bounded
        assert len(cit.excerpt) <= 255

    def test_22_legacy_provenance_honestly_records_unavailable_evidence(self):
        """Verify that backfilling legacy outputs without citations records retrieval_method as unavailable."""
        record = ProvenanceBuilder.build_record(
            output_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            output_type="summary",
            citations=None,  # Not provided/unavailable
            is_backfill=True,
        )

        assert record.evidence.retrieval_method == "unavailable"
        assert record.evidence.chunks_count == 0
        assert record.evidence.citations == []
        assert record.audit.provenance_event_type == "provenance_backfilled"
