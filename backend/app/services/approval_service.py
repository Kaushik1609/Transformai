"""
TransformIQ / KaryaSetu AI — Approval Service (Phase 2F)

Orchestrates human approval, destination-scoped policy gating,
verification snapshotting, stale-approval detection, and release enforcement.

Rules:
- Owner-only project-scoped boundary (no admin bypass).
- Destination-scoped approval.
- Phase 2D supremacy: An approval can NEVER override a Phase 2D BLOCK.
- Fails closed on invalid inputs, unverified contradictions, or stale snapshots.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.audit import emit_security_event
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.verification_result import VerificationResult
from app.policy.approval import (
    ApprovalAction,
    ApprovalStatus,
    DestinationApprovalRecord,
    InvalidApprovalTransitionError,
    OutputApprovalMetadata,
    PolicyHardBlockedError,
    evaluate_initial_approval_status,
    generate_approval_id,
    validate_approval_transition,
)
from app.policy.classification import (
    DEFAULT_CLASSIFICATION,
    InformationClassification,
    normalize_classification,
    resolve_source_classification,
)
from app.policy.dissemination import (
    DisseminationDestination,
    get_dissemination_engine,
    normalize_destination,
)

logger = structlog.get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def resolve_output_classification(
    db: AsyncSession, output: Output
) -> InformationClassification:
    """Resolve the authoritative InformationClassification for an output."""
    job_res = await db.execute(
        select(TransformationJob).where(TransformationJob.id == output.job_id)
    )
    job = job_res.scalar_one_or_none()
    if job:
        if job.source_id:
            src_res = await db.execute(select(Source).where(Source.id == job.source_id))
            src = src_res.scalar_one_or_none()
            if src and src.source_metadata and isinstance(src.source_metadata, dict):
                return resolve_source_classification(src.source_metadata)
        if hasattr(job, "parameters") and isinstance(getattr(job, "parameters"), dict):
            raw = getattr(job, "parameters").get("classification")
            if raw:
                try:
                    return normalize_classification(raw)
                except Exception:
                    pass
        if job.requested_outputs and isinstance(job.requested_outputs, dict):
            raw = job.requested_outputs.get("classification")
            if raw:
                try:
                    return normalize_classification(raw)
                except Exception:
                    pass
    return DEFAULT_CLASSIFICATION


async def _load_source_for_output(
    db: AsyncSession, output: Output
) -> Source | None:
    """Fetch the Source record associated with an output's transformation job."""
    job_res = await db.execute(
        select(TransformationJob).where(TransformationJob.id == output.job_id)
    )
    job = job_res.scalar_one_or_none()
    if job and job.source_id:
        src_res = await db.execute(select(Source).where(Source.id == job.source_id))
        return src_res.scalar_one_or_none()
    return None


async def _load_latest_verification_result(
    db: AsyncSession, output_id: uuid.UUID
) -> VerificationResult | None:
    """Load the most recent VerificationResult for an output."""
    res = await db.execute(
        select(VerificationResult)
        .where(VerificationResult.output_id == output_id)
        .order_by(VerificationResult.created_at.desc())
    )
    return res.scalars().first()


async def get_or_initialize_output_approval(
    db: AsyncSession,
    output: Output,
    *,
    persist: bool = True,
) -> OutputApprovalMetadata:
    """Get the current approval metadata for an output, lazily evaluating missing destinations.

    Fails closed: If any destination is uninitialized, evaluates Phase 2D policy and
    assigns the appropriate initial status (HARD_BLOCKED, NOT_REQUIRED, PENDING_APPROVAL).
    """
    existing_meta = dict(output.output_metadata or {})
    raw_approval = existing_meta.get("approval")
    classification = await resolve_output_classification(db, output)
    engine = get_dissemination_engine()

    dest_records: dict[str, DestinationApprovalRecord] = {}
    latest_id: str | None = None

    if isinstance(raw_approval, dict):
        raw_dests = raw_approval.get("destinations", {})
        latest_id = raw_approval.get("latest_approval_id")
        if isinstance(raw_dests, dict):
            for k, v in raw_dests.items():
                if isinstance(v, dict):
                    try:
                        dest_records[k] = DestinationApprovalRecord.model_validate(v)
                    except Exception:
                        pass

    # Ensure all canonical destinations are evaluated
    modified = False
    for dest in DisseminationDestination:
        dest_key = dest.value
        dissem_decision = engine.evaluate(
            classification=classification,
            destination=dest,
            output_type=output.output_type,
        )

        if dest_key not in dest_records:
            initial_status = evaluate_initial_approval_status(
                classification=classification,
                destination=dest,
                dissemination_decision=dissem_decision,
            )
            dest_records[dest_key] = DestinationApprovalRecord(
                destination=dest_key,
                approval_status=initial_status.value,
                policy_reason=dissem_decision.reason,
                classification_snapshot=classification.value,
                policy_id_snapshot=engine.POLICY_ID,
            )
            modified = True
        else:
            # Re-check Phase 2D supremacy: if policy has become BLOCK, force HARD_BLOCKED
            if not dissem_decision.allowed and dest_records[dest_key].approval_status != ApprovalStatus.HARD_BLOCKED.value:
                dest_records[dest_key].approval_status = ApprovalStatus.HARD_BLOCKED.value
                dest_records[dest_key].policy_reason = dissem_decision.reason
                modified = True

    approval_metadata = OutputApprovalMetadata(
        destinations=dest_records,
        latest_approval_id=latest_id,
    )

    if modified and persist:
        existing_meta["approval"] = approval_metadata.model_dump(mode="json")
        output.output_metadata = existing_meta
        db.add(output)
        await db.flush()

    return approval_metadata


async def submit_output_approval(
    db: AsyncSession,
    *,
    output: Output,
    current_user: CurrentUser,
    destination: DisseminationDestination | str,
    action: ApprovalAction | str,
    comments: str | None = None,
    rejection_reason: str | None = None,
) -> DestinationApprovalRecord:
    """Submit a human approval or rejection decision for a specific destination.

    Enforces:
    1. Output status must be 'completed'.
    2. Phase 2D supremacy: Destination cannot be hard-blocked by policy.
    3. Verification check: Fact verification overall_status must not be 'failed'.
    4. Transition validity: REJECTED is terminal; double approval is prohibited.
    5. Rejection strictly requires a non-empty rejection_reason.
    6. Emits structured audit events.
    7. Synchronizes latest approval ID into provenance extensions.
    """
    if output.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Output {output.id} is in status '{output.status}' (only completed "
                "outputs can be evaluated for approval)."
            ),
        )

    norm_dest = normalize_destination(destination)
    norm_action = ApprovalAction(str(action).lower())
    classification = await resolve_output_classification(db, output)
    engine = get_dissemination_engine()

    # Step 1: Phase 2D Supremacy check
    dissem_decision = engine.evaluate(
        classification=classification,
        destination=norm_dest,
        output_type=output.output_type,
    )
    if not dissem_decision.allowed:
        emit_security_event(
            "approval_attempt_denied",
            outcome="denied",
            user_id=str(current_user.id),
            reason=f"Phase 2D hard-block: {dissem_decision.reason}",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "classification": classification.value,
                "attempted_action": norm_action.value,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Cannot approve destination '{norm_dest.value}': prohibited by "
                f"Phase 2D dissemination policy for classification '{classification.value}'."
            ),
        )

    # Step 2: Verification check
    vr = await _load_latest_verification_result(db, output.id)
    if vr and vr.overall_status == "failed" and norm_action == ApprovalAction.APPROVE:
        emit_security_event(
            "approval_attempt_denied",
            outcome="denied",
            user_id=str(current_user.id),
            reason="Fact verification overall_status is 'failed'.",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "verification_status": vr.overall_status,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot approve output with failed fact verification.",
        )

    # Step 3: Load existing approval metadata
    approval_meta = await get_or_initialize_output_approval(db, output, persist=False)
    current_rec = approval_meta.destinations.get(norm_dest.value)
    current_status = (
        current_rec.approval_status
        if current_rec
        else ApprovalStatus.PENDING_APPROVAL.value
    )

    # Step 4: Validate transition
    try:
        next_status = validate_approval_transition(
            current_status=current_status,
            action=norm_action,
            rejection_reason=rejection_reason,
        )
    except PolicyHardBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except InvalidApprovalTransitionError as exc:
        emit_security_event(
            "approval_invalid_transition",
            outcome="error",
            user_id=str(current_user.id),
            reason=str(exc),
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "current_status": current_status,
                "attempted_action": norm_action.value,
            },
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    # Step 5: Check project ownership for self-approval flag
    job_res = await db.execute(
        select(TransformationJob).where(TransformationJob.id == output.job_id)
    )
    job = job_res.scalar_one_or_none()
    project_owner_id: str | None = None
    if job:
        proj_res = await db.execute(
            select(Project).where(Project.id == job.project_id)
        )
        proj = proj_res.scalar_one_or_none()
        if proj:
            project_owner_id = str(proj.user_id)

    is_self_approved = bool(
        project_owner_id and str(current_user.id) == project_owner_id
    )

    # Step 6: Build snapshot & record
    source = await _load_source_for_output(db, output)
    source_hash = None
    if source and source.source_metadata and isinstance(source.source_metadata, dict):
        source_hash = source.source_metadata.get("content_hash") or source.source_metadata.get("sha256")

    approval_id = generate_approval_id()
    now_iso = _utcnow_iso()

    updated_rec = DestinationApprovalRecord(
        destination=norm_dest.value,
        approval_status=next_status.value,
        approval_id=approval_id,
        decision=next_status.value,
        approver_id=str(current_user.id),
        approver_email=current_user.email,
        approver_role=current_user.role,
        approved_at=now_iso,
        rejection_reason=rejection_reason if norm_action == ApprovalAction.REJECT else None,
        comments=comments,
        self_approved=is_self_approved,
        policy_reason=dissem_decision.reason,
        classification_snapshot=classification.value,
        verification_status_snapshot=vr.overall_status if vr else "unverified",
        source_hash_snapshot=source_hash,
        policy_id_snapshot=engine.POLICY_ID,
    )

    approval_meta.destinations[norm_dest.value] = updated_rec
    approval_meta.latest_approval_id = approval_id

    # Persist to output_metadata
    out_meta = dict(output.output_metadata or {})
    out_meta["approval"] = approval_meta.model_dump(mode="json")

    # Link approval_id into provenance extension if present (Phase 2E integration)
    prov = out_meta.get("provenance")
    if isinstance(prov, dict):
        exts = dict(prov.get("extensions") or {})
        exts["approval_id"] = approval_id
        prov["extensions"] = exts
        out_meta["provenance"] = prov

    output.output_metadata = out_meta
    db.add(output)
    await db.flush()

    # Step 7: Emit Audit Event
    if norm_action == ApprovalAction.APPROVE:
        emit_security_event(
            "output_approved",
            outcome="allowed",
            user_id=str(current_user.id),
            reason=comments or "human_operator_approved",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "approval_id": approval_id,
                "classification": classification.value,
                "self_approved": is_self_approved,
            },
        )
    else:
        emit_security_event(
            "output_rejected",
            outcome="denied",
            user_id=str(current_user.id),
            reason=rejection_reason or "human_operator_rejected",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "approval_id": approval_id,
                "rejection_reason": rejection_reason,
            },
        )

    return updated_rec


async def verify_release_eligibility(
    db: AsyncSession,
    *,
    output: Output,
    destination: DisseminationDestination | str,
    user_id: uuid.UUID | str | None = None,
) -> tuple[bool, str]:
    """Authoritatively verify whether an output is eligible for release/dissemination.

    Evaluates:
    1. Output status must be 'completed'.
    2. Current source classification (Phase 2A).
    3. Real-time Phase 2D dissemination policy (Phase 2D supremacy).
    4. Real-time fact verification state (cannot release failed verification).
    5. Destination-scoped approval state.
    6. Stale approval detection (classification or source hash changes).

    Returns:
        (is_eligible: bool, reason: str)
    """
    if output.status != "completed":
        return False, f"Output is not completed (current status: '{output.status}')."

    norm_dest = normalize_destination(destination)
    classification = await resolve_output_classification(db, output)
    engine = get_dissemination_engine()

    # Step 1: Real-time Phase 2D policy re-evaluation
    dissem_decision = engine.evaluate(
        classification=classification,
        destination=norm_dest,
        output_type=output.output_type,
    )
    if not dissem_decision.allowed:
        emit_security_event(
            "release_blocked",
            outcome="blocked",
            user_id=str(user_id) if user_id else "unknown",
            reason=f"Phase 2D policy blocked: {dissem_decision.reason}",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "classification": classification.value,
            },
        )
        return False, f"Dissemination blocked by policy: {dissem_decision.reason}"

    # Step 2: Verification check
    vr = await _load_latest_verification_result(db, output.id)
    if vr and vr.overall_status == "failed":
        emit_security_event(
            "release_blocked",
            outcome="blocked",
            user_id=str(user_id) if user_id else "unknown",
            reason="Fact verification overall_status is 'failed'.",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "verification_status": vr.overall_status,
            },
        )
        return False, "Release blocked: Fact verification failed for this output."

    # Step 3: Approval state inspection
    approval_meta = await get_or_initialize_output_approval(db, output, persist=True)
    rec = approval_meta.destinations.get(norm_dest.value)
    curr_status = rec.approval_status if rec else ApprovalStatus.PENDING_APPROVAL.value

    if curr_status == ApprovalStatus.NOT_REQUIRED.value:
        emit_security_event(
            "release_allowed",
            outcome="allowed",
            user_id=str(user_id) if user_id else "unknown",
            reason="Human approval not required for this destination/classification.",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "classification": classification.value,
            },
        )
        return True, "Release allowed: Human approval not required."

    if curr_status != ApprovalStatus.APPROVED.value:
        emit_security_event(
            "release_blocked",
            outcome="blocked",
            user_id=str(user_id) if user_id else "unknown",
            reason=f"Destination requires approval; current status is '{curr_status}'.",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "approval_status": curr_status,
            },
        )
        return False, (
            f"Release blocked: Destination '{norm_dest.value}' requires human approval "
            f"(current status: '{curr_status}')."
        )

    # Step 4: Stale approval verification
    stale_reason: str | None = None

    # Check classification drift
    if rec and rec.classification_snapshot and rec.classification_snapshot != classification.value:
        stale_reason = (
            f"Classification changed from '{rec.classification_snapshot}' to '{classification.value}'."
        )

    # Check source content hash drift
    if not stale_reason and rec and rec.source_hash_snapshot:
        source = await _load_source_for_output(db, output)
        current_hash = None
        if source and source.source_metadata and isinstance(source.source_metadata, dict):
            current_hash = source.source_metadata.get("content_hash") or source.source_metadata.get("sha256")
        if current_hash and current_hash != rec.source_hash_snapshot:
            stale_reason = "Source content has been modified since approval was granted."

    if stale_reason:
        # Transition to REVOKED
        if rec:
            rec.approval_status = ApprovalStatus.REVOKED.value
            rec.comments = f"Automatically revoked: {stale_reason}"
            out_meta = dict(output.output_metadata or {})
            out_meta["approval"] = approval_meta.model_dump(mode="json")
            output.output_metadata = out_meta
            db.add(output)
            await db.flush()

        emit_security_event(
            "stale_approval_detected",
            outcome="blocked",
            user_id=str(user_id) if user_id else "unknown",
            reason=stale_reason,
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
                "stale_reason": stale_reason,
            },
        )
        emit_security_event(
            "release_blocked",
            outcome="blocked",
            user_id=str(user_id) if user_id else "unknown",
            reason=f"Approval invalidated: {stale_reason}",
            details={
                "output_id": str(output.id),
                "destination": norm_dest.value,
            },
        )
        return False, f"Release blocked: Approval is stale ({stale_reason})."

    # Step 5: Verified release
    emit_security_event(
        "release_allowed",
        outcome="allowed",
        user_id=str(user_id) if user_id else "unknown",
        reason="Human approval verified.",
        details={
            "output_id": str(output.id),
            "destination": norm_dest.value,
            "approval_id": rec.approval_id if rec else None,
        },
    )
    return True, "Release allowed: Human approval verified."
