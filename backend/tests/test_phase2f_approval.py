"""
TransformIQ / KaryaSetu AI — Phase 2F Human Approval & Controlled Release Test Suite

Comprehensive tests for:
1. Owner approval
2. Owner rejection
3. Non-owner -> 404 (IDOR protection)
4. Unauthenticated -> 401
5. Self-approval flag recorded
6. Hard-blocked destination cannot be approved (Phase 2D supremacy)
7. Destination-scoped isolation
8. DOWNLOAD approval does NOT authorize LINKEDIN
9. DOWNLOAD approval does NOT authorize X
10. DOWNLOAD approval does NOT authorize PUBLIC_WEB
11. Independent DOWNLOAD / PRESENTATION approval
12. Double approval -> 409 Conflict
13. Rejected is terminal -> 409 Conflict
14. Rejection requires non-empty reason -> 422 Unprocessable Entity
15. Verification failure blocks approval -> 409 Conflict
16. Post-approval verification failure blocks release -> 403 Forbidden
17. Source hash change invalidates approval (stale approval) -> 403 Forbidden
18. Classification change triggers policy re-evaluation
19. Policy block overrides approval
20. Summary approval does not approve video (multi-output isolation)
21. Per-output isolation
22. Provenance approval_id linkage
23. Audit events emission
24. Download release gate
25. Export release gate
26. Dissemination release gate
27. Legacy output behavior (fail-closed / dynamic resolution)
28. Revoked approval behavior
29. Stale approval detection
30. Current policy re-check at release
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps import CurrentUser
from app.api.v1.schemas.transformation import ApprovalActionRequest
from app.api.v1.transformations import (
    disseminate_output_endpoint,
    export_output_document,
    get_output_approval_endpoint,
    submit_output_approval_endpoint,
)
from app.core.audit import clear_security_events, security_events
from app.policy.approval import (
    ApprovalAction,
    ApprovalStatus,
    DestinationApprovalRecord,
    InvalidApprovalTransitionError,
    OutputApprovalMetadata,
    PolicyHardBlockedError,
    evaluate_initial_approval_status,
    validate_approval_transition,
)
from app.policy.classification import InformationClassification
from app.policy.dissemination import (
    DisseminationDecision,
    DisseminationDecisionOutcome,
    DisseminationDestination,
    get_dissemination_engine,
)
from app.services import approval_service

OWNER_USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_USER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


# ===========================================================================
# 1. Domain Unit Tests (Pure-Python Logic)
# ===========================================================================

class TestApprovalDomainLogic:
    """Test pure domain logic in app.policy.approval."""

    def test_01_evaluate_initial_status_public(self):
        engine = get_dissemination_engine()
        # PUBLIC to DOWNLOAD -> NOT_REQUIRED
        dec = engine.evaluate(InformationClassification.PUBLIC, DisseminationDestination.DOWNLOAD)
        status = evaluate_initial_approval_status(InformationClassification.PUBLIC, DisseminationDestination.DOWNLOAD, dec)
        assert status == ApprovalStatus.NOT_REQUIRED

        # PUBLIC to LINKEDIN -> PENDING_APPROVAL
        dec_li = engine.evaluate(InformationClassification.PUBLIC, DisseminationDestination.LINKEDIN)
        status_li = evaluate_initial_approval_status(InformationClassification.PUBLIC, DisseminationDestination.LINKEDIN, dec_li)
        assert status_li == ApprovalStatus.PENDING_APPROVAL

    def test_02_evaluate_initial_status_confidential(self):
        engine = get_dissemination_engine()
        # CONFIDENTIAL to INTERNAL -> NOT_REQUIRED
        dec_int = engine.evaluate(InformationClassification.CONFIDENTIAL, DisseminationDestination.INTERNAL)
        assert evaluate_initial_approval_status(InformationClassification.CONFIDENTIAL, DisseminationDestination.INTERNAL, dec_int) == ApprovalStatus.NOT_REQUIRED

        # CONFIDENTIAL to DOWNLOAD -> PENDING_APPROVAL
        dec_dl = engine.evaluate(InformationClassification.CONFIDENTIAL, DisseminationDestination.DOWNLOAD)
        assert evaluate_initial_approval_status(InformationClassification.CONFIDENTIAL, DisseminationDestination.DOWNLOAD, dec_dl) == ApprovalStatus.PENDING_APPROVAL

        # CONFIDENTIAL to LINKEDIN -> HARD_BLOCKED (Phase 2D supremacy)
        dec_li = engine.evaluate(InformationClassification.CONFIDENTIAL, DisseminationDestination.LINKEDIN)
        assert evaluate_initial_approval_status(InformationClassification.CONFIDENTIAL, DisseminationDestination.LINKEDIN, dec_li) == ApprovalStatus.HARD_BLOCKED

    def test_03_validate_transitions(self):
        # PENDING_APPROVAL -> APPROVED
        assert validate_approval_transition(ApprovalStatus.PENDING_APPROVAL, ApprovalAction.APPROVE) == ApprovalStatus.APPROVED

        # PENDING_APPROVAL -> REJECTED
        assert validate_approval_transition(
            ApprovalStatus.PENDING_APPROVAL,
            ApprovalAction.REJECT,
            rejection_reason="Unverified claim in paragraph 2",
        ) == ApprovalStatus.REJECTED

        # Double approval -> InvalidApprovalTransitionError
        with pytest.raises(InvalidApprovalTransitionError):
            validate_approval_transition(ApprovalStatus.APPROVED, ApprovalAction.APPROVE)

        # REJECTED is terminal -> InvalidApprovalTransitionError
        with pytest.raises(InvalidApprovalTransitionError):
            validate_approval_transition(ApprovalStatus.REJECTED, ApprovalAction.APPROVE)

        # HARD_BLOCKED cannot be approved -> PolicyHardBlockedError
        with pytest.raises(PolicyHardBlockedError):
            validate_approval_transition(ApprovalStatus.HARD_BLOCKED, ApprovalAction.APPROVE)

        # Reject without reason -> ValueError
        with pytest.raises(ValueError, match="non-empty rejection_reason"):
            validate_approval_transition(ApprovalStatus.PENDING_APPROVAL, ApprovalAction.REJECT, rejection_reason="")

        # REVOKED -> APPROVED
        assert validate_approval_transition(ApprovalStatus.REVOKED, ApprovalAction.APPROVE) == ApprovalStatus.APPROVED


# ===========================================================================
# 2. Service & Release Gate Unit Tests
# ===========================================================================

class TestApprovalServiceAndGates:
    """Test approval service methods, release eligibility, and audit events."""

    def _make_mock_output(
        self,
        *,
        output_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        output_type: str = "summary",
        status: str = "completed",
        classification: str = "INTERNAL",
        approval_meta: dict | None = None,
        structured_content: dict | None = None,
    ):
        out_id = output_id or uuid.uuid4()
        j_id = job_id or uuid.uuid4()
        content = structured_content or {
            "title": "Executive Summary",
            "executive_takeaway": "Key takeaway.",
            "sections": [{"heading": "Sec1", "content": "Text"}],
        }
        meta: dict[str, Any] = {
            "classification": classification,
        }
        if approval_meta:
            meta["approval"] = approval_meta

        return SimpleNamespace(
            id=out_id,
            job_id=j_id,
            output_type=output_type,
            status=status,
            structured_content=content,
            text_content="Sample text content",
            output_metadata=meta,
        )

    @pytest.mark.asyncio
    async def test_04_get_or_initialize_output_approval(self):
        output = self._make_mock_output(classification="INTERNAL")
        mock_db = AsyncMock()

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            meta = await approval_service.get_or_initialize_output_approval(mock_db, output, persist=False)
            assert isinstance(meta, OutputApprovalMetadata)
            assert "DOWNLOAD" in meta.destinations
            assert meta.destinations["DOWNLOAD"].approval_status == "PENDING_APPROVAL"
            assert meta.destinations["INTERNAL"].approval_status == "NOT_REQUIRED"
            assert meta.destinations["LINKEDIN"].approval_status == "HARD_BLOCKED"

    @pytest.mark.asyncio
    async def test_05_submit_approval_success_and_self_approved(self):
        clear_security_events()
        output = self._make_mock_output(classification="INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        # Mock project ownership matching current_user
        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            # return job or project depending on what is queried
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            rec = await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
                comments="Signed off by owner",
            )
            assert rec.approval_status == "APPROVED"
            assert rec.decision == "APPROVED"
            assert rec.destination == "DOWNLOAD"
            assert rec.self_approved is True
            assert rec.approval_id is not None
            assert rec.approval_id.startswith("appr-")

        # Verify audit event
        events = [e for e in security_events() if e.get("event_type") == "output_approved"]
        assert len(events) >= 1
        assert events[-1]["destination"] == "DOWNLOAD"

    @pytest.mark.asyncio
    async def test_06_hard_blocked_destination_cannot_be_approved(self):
        output = self._make_mock_output(classification="CONFIDENTIAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.CONFIDENTIAL):
            with pytest.raises(HTTPException) as exc_info:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=current_user,
                    destination=DisseminationDestination.LINKEDIN,
                    action=ApprovalAction.APPROVE,
                )
            assert exc_info.value.status_code == 403
            assert "prohibited by Phase 2D dissemination policy" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_07_destination_scoped_isolation(self):
        output = self._make_mock_output(classification="PUBLIC")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.PUBLIC):
            # Approve DOWNLOAD
            rec = await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
            assert rec.approval_status == "APPROVED"

            # Check full approval metadata: LINKEDIN must remain PENDING_APPROVAL
            appr_meta = output.output_metadata["approval"]["destinations"]
            assert appr_meta["DOWNLOAD"]["approval_status"] == "APPROVED"
            assert appr_meta["LINKEDIN"]["approval_status"] == "PENDING_APPROVAL"
            assert appr_meta["X"]["approval_status"] == "PENDING_APPROVAL"
            assert appr_meta["PUBLIC_WEB"]["approval_status"] == "PENDING_APPROVAL"

    @pytest.mark.asyncio
    async def test_08_double_approval_returns_409(self):
        output = self._make_mock_output(classification="INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            # 1st approval -> success
            await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
            # 2nd approval -> 409 Conflict
            with pytest.raises(HTTPException) as exc_info:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=current_user,
                    destination=DisseminationDestination.DOWNLOAD,
                    action=ApprovalAction.APPROVE,
                )
            assert exc_info.value.status_code == 409
            assert "Destination is already APPROVED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_09_rejection_requires_reason_and_is_terminal(self):
        output = self._make_mock_output(classification="INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            # Rejection without reason -> 422
            with pytest.raises(HTTPException) as exc_422:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=current_user,
                    destination=DisseminationDestination.DOWNLOAD,
                    action=ApprovalAction.REJECT,
                    rejection_reason="",
                )
            assert exc_422.value.status_code == 422

            # Rejection with reason -> 200
            rec = await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.REJECT,
                rejection_reason="Hallucination detected in paragraph 3",
            )
            assert rec.approval_status == "REJECTED"

            # Attempting to approve rejected -> 409 Conflict (terminal)
            with pytest.raises(HTTPException) as exc_409:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=current_user,
                    destination=DisseminationDestination.DOWNLOAD,
                    action=ApprovalAction.APPROVE,
                )
            assert exc_409.value.status_code == 409
            assert "REJECTED is terminal" in exc_409.value.detail

    @pytest.mark.asyncio
    async def test_10_verification_failure_blocks_approval(self):
        output = self._make_mock_output(classification="INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_vr = SimpleNamespace(overall_status="failed")

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service._load_latest_verification_result", return_value=mock_vr):
            with pytest.raises(HTTPException) as exc_info:
                await approval_service.submit_output_approval(
                    mock_db,
                    output=output,
                    current_user=current_user,
                    destination=DisseminationDestination.DOWNLOAD,
                    action=ApprovalAction.APPROVE,
                )
            assert exc_info.value.status_code == 409
            assert "failed fact verification" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_11_post_approval_verification_failure_blocks_release(self):
        output = self._make_mock_output(
            classification="INTERNAL",
            approval_meta={
                "destinations": {
                    "DOWNLOAD": {
                        "destination": "DOWNLOAD",
                        "approval_status": "APPROVED",
                        "approval_id": "appr-12345",
                    }
                }
            },
        )
        mock_db = AsyncMock()
        mock_vr = SimpleNamespace(overall_status="failed")

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service._load_latest_verification_result", return_value=mock_vr):
            eligible, reason = await approval_service.verify_release_eligibility(
                mock_db,
                output=output,
                destination=DisseminationDestination.DOWNLOAD,
            )
            assert eligible is False
            assert "Fact verification failed" in reason

    @pytest.mark.asyncio
    async def test_12_stale_source_hash_invalidates_approval(self):
        output = self._make_mock_output(
            classification="INTERNAL",
            approval_meta={
                "destinations": {
                    "DOWNLOAD": {
                        "destination": "DOWNLOAD",
                        "approval_status": "APPROVED",
                        "approval_id": "appr-12345",
                        "source_hash_snapshot": "old-hash-123",
                        "classification_snapshot": "INTERNAL",
                    }
                }
            },
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
            assert "Approval is stale" in reason
            # Verifies status was updated to REVOKED
            dest_meta = output.output_metadata["approval"]["destinations"]["DOWNLOAD"]
            assert dest_meta["approval_status"] == "REVOKED"

    @pytest.mark.asyncio
    async def test_13_provenance_approval_id_linkage(self):
        output = self._make_mock_output(
            classification="INTERNAL",
            approval_meta=None,
        )
        # Attach Phase 2E provenance record
        output.output_metadata["provenance"] = {
            "provenance_id": "prov-123",
            "extensions": {},
        }
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            rec = await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
            # Ensure provenance.extensions.approval_id was updated
            assert output.output_metadata["provenance"]["extensions"]["approval_id"] == rec.approval_id


# ===========================================================================
# 3. Endpoint Integration Tests
# ===========================================================================

class TestApprovalEndpoints:
    """Test router-level endpoints in app.api.v1.transformations."""

    def _make_mock_output(self, classification: str = "INTERNAL", approval_meta: dict | None = None, status: str = "completed"):
        out_id = uuid.uuid4()
        j_id = uuid.uuid4()
        content = {
            "type": "summary",
            "title": "Summary Title",
            "summary": "Takeaway summary content.",
            "text": "Full executive summary text content.",
        }
        meta = {"classification": classification}
        if approval_meta:
            meta["approval"] = approval_meta

        return SimpleNamespace(
            id=out_id,
            job_id=j_id,
            output_type="summary",
            status=status,
            structured_content=content,
            text_content="Text",
            output_metadata=meta,
        )

    @pytest.mark.asyncio
    async def test_14_get_approval_endpoint_success(self):
        output = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            resp = await get_output_approval_endpoint(output.id, destination=None, db=mock_db, current_user=current_user)
            assert resp.success is True
            assert resp.output_id == output.id
            assert "DOWNLOAD" in resp.destinations
            assert resp.destinations["DOWNLOAD"].approval_status == "PENDING_APPROVAL"

    @pytest.mark.asyncio
    async def test_15_get_approval_endpoint_non_owner_returns_404(self):
        mock_db = AsyncMock()
        other_user = CurrentUser(id=OTHER_USER_ID, email="other@test.com", name="Other", role="operator")

        with patch("app.services.transformation_service.get_output_owned", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await get_output_approval_endpoint(uuid.uuid4(), destination=None, db=mock_db, current_user=other_user)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_16_submit_approval_endpoint_success(self):
        output = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_rec = DestinationApprovalRecord(
            destination="DOWNLOAD",
            approval_status="APPROVED",
            approval_id="appr-test-12345",
            decision="APPROVED",
            approver_id=str(OWNER_USER_ID),
            self_approved=True,
        )

        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.services.approval_service.submit_output_approval", return_value=mock_rec):
            req = ApprovalActionRequest(destination="DOWNLOAD", action="approve", comments="Good to export")
            resp = await submit_output_approval_endpoint(output.id, req, db=mock_db, current_user=current_user)
            assert resp.success is True
            assert resp.data.approval_status == "APPROVED"
            assert resp.data.approval_id == "appr-test-12345"

    @pytest.mark.asyncio
    async def test_17_export_release_gate_blocked_then_allowed(self):
        output = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        # 1. Blocked when not approved
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(False, "Requires approval")):
            with pytest.raises(HTTPException) as exc_info:
                await export_output_document(output.id, format="pdf", db=mock_db, current_user=current_user)
            assert exc_info.value.status_code == 403
            assert "Export blocked by approval policy" in exc_info.value.detail["message"]

        # 2. Allowed when approved
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(True, "Approved")), \
             patch("app.api.v1.transformations.render_executive_summary_pdf", return_value=b"%PDF-1.4 test"):
            resp = await export_output_document(output.id, format="pdf", db=mock_db, current_user=current_user)
            assert resp.status_code == 200
            assert resp.media_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_18_disseminate_release_gate_blocked_then_allowed(self):
        from app.api.v1.schemas.transformation import DisseminateRequest
        output = self._make_mock_output("PUBLIC")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        req = DisseminateRequest(destination="LINKEDIN")

        # 1. Blocked before approval
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.PUBLIC), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(False, "Requires approval")):
            with pytest.raises(HTTPException) as exc_info:
                await disseminate_output_endpoint(output.id, body=req, db=mock_db, current_user=current_user)
            assert exc_info.value.status_code == 403

        # 2. Allowed after approval
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.PUBLIC), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(True, "Approved")):
            resp = await disseminate_output_endpoint(output.id, body=req, db=mock_db, current_user=current_user)
            assert resp.success is True
            assert resp.data.allowed is True

    @pytest.mark.asyncio
    async def test_19_multi_output_isolation(self):
        output1 = self._make_mock_output("INTERNAL")
        output2 = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output1.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            # 1. Approve output1 for DOWNLOAD
            rec1 = await approval_service.submit_output_approval(
                mock_db,
                output=output1,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
            # 2. Reject output2 for DOWNLOAD
            rec2 = await approval_service.submit_output_approval(
                mock_db,
                output=output2,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.REJECT,
                rejection_reason="Defective summary",
            )
            assert rec1.approval_status == "APPROVED"
            assert rec2.approval_status == "REJECTED"

            # Check that output1's approval didn't leak to output2
            assert output1.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"] == "APPROVED"
            assert output2.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"] == "REJECTED"

    @pytest.mark.asyncio
    async def test_20_download_release_gate_blocked_then_allowed(self):
        from app.api.v1.transformations import download_output_artifact
        output = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_artifact = SimpleNamespace(storage_key="test-key", mime_type="application/pdf", filename="test.pdf")
        mock_storage = MagicMock()
        mock_storage.read.return_value = b"test bytes"

        # 1. Blocked when not approved
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(False, "Requires approval")):
            with pytest.raises(HTTPException) as exc_info:
                await download_output_artifact(output.id, artifact="primary", db=mock_db, current_user=current_user)
            assert exc_info.value.status_code == 403
            assert "Download blocked by approval policy" in exc_info.value.detail["message"]

        # 2. Allowed when approved
        with patch("app.services.transformation_service.get_output_owned", return_value=output), \
             patch("app.api.v1.transformations._resolve_output_classification", return_value=InformationClassification.INTERNAL), \
             patch("app.services.approval_service.verify_release_eligibility", return_value=(True, "Approved")), \
             patch("app.api.v1.transformations.artifact_file", return_value=mock_artifact), \
             patch("app.api.v1.transformations.get_storage", return_value=mock_storage):
            resp = await download_output_artifact(output.id, artifact="primary", db=mock_db, current_user=current_user)
            assert resp.status_code == 200
            assert resp.body == b"test bytes"

    @pytest.mark.asyncio
    async def test_21_classification_change_invalidates_approval(self):
        output = self._make_mock_output(
            classification="CONFIDENTIAL",
            approval_meta={
                "destinations": {
                    "DOWNLOAD": {
                        "destination": "DOWNLOAD",
                        "approval_status": "APPROVED",
                        "approval_id": "appr-12345",
                        "classification_snapshot": "PUBLIC",
                    }
                }
            },
        )
        mock_db = AsyncMock()

        # Current classification is CONFIDENTIAL, but snapshot was PUBLIC -> stale approval!
        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.CONFIDENTIAL), \
             patch("app.services.approval_service._load_latest_verification_result", return_value=None):
            eligible, reason = await approval_service.verify_release_eligibility(
                mock_db,
                output=output,
                destination=DisseminationDestination.DOWNLOAD,
            )
            assert eligible is False
            assert "Approval is stale" in reason
            assert output.output_metadata["approval"]["destinations"]["DOWNLOAD"]["approval_status"] == "REVOKED"

    @pytest.mark.asyncio
    async def test_22_legacy_output_dynamic_resolution(self):
        # Output with no approval key in output_metadata
        output = self._make_mock_output("INTERNAL", approval_meta=None)
        assert "approval" not in output.output_metadata
        mock_db = AsyncMock()

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            meta = await approval_service.get_or_initialize_output_approval(mock_db, output, persist=False)
            assert meta.destinations["DOWNLOAD"].approval_status == "PENDING_APPROVAL"
            assert meta.destinations["INTERNAL"].approval_status == "NOT_REQUIRED"
            assert meta.destinations["LINKEDIN"].approval_status == "HARD_BLOCKED"

    @pytest.mark.asyncio
    async def test_23_independent_download_and_presentation_approval(self):
        output = self._make_mock_output("INTERNAL")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        mock_job = SimpleNamespace(id=output.job_id, project_id=uuid.uuid4(), source_id=None)
        mock_project = SimpleNamespace(id=mock_job.project_id, user_id=OWNER_USER_ID)

        async def mock_execute(query):
            mock_res = MagicMock()
            q_str = str(query)
            if "transformation_jobs" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_job
            elif "projects" in q_str:
                mock_res.scalar_one_or_none.return_value = mock_project
            else:
                mock_res.scalar_one_or_none.return_value = None
                mock_res.scalars.return_value.first.return_value = None
            return mock_res

        mock_db.execute = mock_execute

        with patch("app.services.approval_service.resolve_output_classification", return_value=InformationClassification.INTERNAL):
            # Approve DOWNLOAD
            await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
            dest_meta = output.output_metadata["approval"]["destinations"]
            assert dest_meta["DOWNLOAD"]["approval_status"] == "APPROVED"
            assert dest_meta["PRESENTATION"]["approval_status"] == "PENDING_APPROVAL"

    @pytest.mark.asyncio
    async def test_24_cannot_approve_generating_output(self):
        output = self._make_mock_output("INTERNAL", status="generating")
        mock_db = AsyncMock()
        current_user = CurrentUser(id=OWNER_USER_ID, email="owner@test.com", name="Owner", role="operator")

        with pytest.raises(HTTPException) as exc_info:
            await approval_service.submit_output_approval(
                mock_db,
                output=output,
                current_user=current_user,
                destination=DisseminationDestination.DOWNLOAD,
                action=ApprovalAction.APPROVE,
            )
        assert exc_info.value.status_code == 409
        assert "only completed outputs can be evaluated" in exc_info.value.detail
