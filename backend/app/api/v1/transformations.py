"""
TransformIQ Backend — Transformation Job API Router

Endpoints:
    GET    /api/v1/projects/{project_id}/transformations  (job history)
    POST   /api/v1/transformations
    GET    /api/v1/transformations/{job_id}
    GET    /api/v1/transformations/{job_id}/outputs
    POST   /api/v1/transformations/{job_id}/cancel  (stub — Phase 6)

    GET    /api/v1/outputs/{output_id}
    GET    /api/v1/outputs/{output_id}/verification
    GET    /api/v1/outputs/{output_id}/download
    POST   /api/v1/outputs/{output_id}/export  (DOCX/PDF for text outputs)

Phase 2: persistence only. No job enqueueing, no AI calls.
"""
import uuid
from typing import Any, Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.api.v1.schemas.transformation import (
    ConsistencyConflictResponse,
    ConsistencyResponse,
    ConsistencyResultResponse,
    CrossOutputConsistencyResponse,
    FactVerificationClaimResponse,
    FactVerificationEvidenceResponse,
    FactVerificationResponse,
    FactVerificationResultResponse,
    IntegrityDetailResponse,
    IntegrityRecordResponse,
    IntegrityVerifyResponse,
    OutputDetailResponse,
    OutputListResponse,
    OutputResponse,
    TransformationJobCreate,
    TransformationJobDetailResponse,
    TransformationJobListResponse,
    TransformationJobResponse,
    TrustSignalResponse,
    TrustStatusResponse,
    VerificationListResponse,
    VerificationResultResponse,
    DisseminateRequest,
    DisseminateResponse,
    DisseminationDecisionResponse,
    DisseminationEvaluateRequest,
    DisseminationReportResponse,
    ProvenanceDetailResponse,
    ApprovalActionRequest,
    ApprovalActionResponse,
    ApprovalStatusResponse,
    DestinationApprovalDetail,
    OutputIntegrityDetail,
    OutputIntegrityResponse,
    IntegrityVerifyResponse,
    OutputSignatureDetail,
    OutputSignatureResponse,
    SignatureVerifyResponse,
)
from app.core.ratelimit import rate_limit_bucket
from app.core.config import settings
from app.db.session import get_db
from app.core.metrics import metrics
from app.services import (
    project_service,
    source_service,
    configuration_service,
    transformation_service,
    approval_service,
    integrity_service,
    signature_service,
)
from app.transformation.artifacts import artifact_file, get_storage
from app.transformation.output_schemas import Advisory, ExecutiveSummary
from app.transformation.queue import (
    cancel_transformation_job,
    enqueue_transformation_job,
    get_transformation_queue,
)
from app.transformation.render.docx import (
    DOCX_MIME_TYPE,
    render_advisory_docx,
    render_executive_summary_docx,
)
from app.transformation.service import execute_transformation_job_sync
from app.transformation.render.pdf import (
    PDF_MIME_TYPE,
    render_advisory_pdf,
    render_executive_summary_pdf,
)

logger = structlog.get_logger(__name__)

transformations_router = APIRouter(tags=["transformations"])
outputs_router = APIRouter(tags=["outputs"])
project_transformations_router = APIRouter(tags=["transformations"])


# ---------------------------------------------------------------------------
# Project transformation history
# ---------------------------------------------------------------------------

@project_transformations_router.get(
    "/{project_id}/transformations",
    response_model=TransformationJobListResponse,
    summary="List transformation jobs for a project (history)",
)
async def list_project_transformations(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobListResponse:
    """Return the transformation job history for a project (newest first)."""
    project = await project_service.get_project(
        db, project_id=project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    jobs = await transformation_service.list_jobs_by_project(
        db, project_id=project_id
    )
    return TransformationJobListResponse(
        data=[TransformationJobResponse.model_validate(j) for j in jobs],
        count=len(jobs),
    )


# ---------------------------------------------------------------------------
# Transformation Jobs
# ---------------------------------------------------------------------------

@transformations_router.post(
    "",
    response_model=TransformationJobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a transformation job",
)
async def create_transformation(
    body: TransformationJobCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _: None = Depends(rate_limit_bucket("transformation")),
) -> TransformationJobDetailResponse:
    # Verify project ownership
    project = await project_service.get_project(
        db, project_id=body.project_id, user_id=current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {body.project_id} not found.",
        )
    # Verify source exists in project (source-only / source+prompt modes).
    if body.source_id is not None:
        source = await source_service.get_source(db, source_id=body.source_id)
        if source is None or source.project_id != body.project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {body.source_id} not found in project {body.project_id}.",
            )
    # Verify configuration exists in project
    config = await configuration_service.get_configuration(
        db, configuration_id=body.configuration_id
    )
    if config is None or config.project_id != body.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration {body.configuration_id} not found in project {body.project_id}.",
        )

    # Phase 2A/2B: Deterministic Policy Engine Gate (Pre-AI Enforcement)
    from app.core.audit import emit_security_event
    from app.policy import (
        DEFAULT_CLASSIFICATION,
        PolicyEvaluationContext,
        get_policy_engine,
        resolve_source_classification,
    )

    # 1. Resolve information classification from source or default
    classification = DEFAULT_CLASSIFICATION
    if body.source_id is not None:
        # source was already verified above
        classification = resolve_source_classification(source.source_metadata)

    # 2. Determine requested provider and environment
    requested_provider = (
        (body.llm_provider or settings.LLM_PROVIDER or "openai").strip().lower()
    )
    environment = (settings.ENVIRONMENT or "development").strip().lower()

    # 3. Evaluate deterministic policy
    context = PolicyEvaluationContext(
        classification=classification,
        requested_outputs=body.output_types,
        requested_provider=requested_provider,
        environment=environment,
    )
    policy_engine = get_policy_engine()
    decision = policy_engine.evaluate(context)

    # 4. Record audit event
    emit_security_event(
        "policy_evaluated",
        outcome="allowed" if decision.allowed else "denied",
        user_id=str(current_user.id),
        project_id=str(body.project_id),
        source_id=str(body.source_id) if body.source_id else None,
        reason=decision.reason,
        details={
            "classification": decision.classification.value,
            "processing_route": decision.processing_route,
            "requested_outputs": body.output_types,
            "provider": requested_provider,
            "environment": environment,
            "requires_review": decision.requires_review,
        },
    )

    # 5. Fail closed if not allowed (HTTP 403, 0 jobs, 0 LLM calls, 0 artifacts)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Processing blocked by policy.",
                "reason": decision.reason,
                "classification": decision.classification.value,
                "processing_route": decision.processing_route,
                "requires_review": decision.requires_review,
            },
        )

    # 6. Phase 2C — Pre-Job PolicyRouter Validation
    from app.policy.routing import get_policy_router
    router = get_policy_router()
    route_decision = router.route(
        decision=decision,
        requested_provider=requested_provider,
        requested_model=body.model,
        environment=environment,
    )

    emit_security_event(
        "routing_resolved",
        outcome="routed" if route_decision.allowed else "failed_unavailable",
        user_id=str(current_user.id),
        project_id=str(body.project_id),
        source_id=str(body.source_id) if body.source_id else None,
        reason=route_decision.reason,
        details={
            "provider": route_decision.provider_id,
            "model": route_decision.model_id,
            "route": route_decision.processing_route.value,
            "classification": route_decision.classification.value,
            "error_code": route_decision.error_code,
        },
    )

    if not route_decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Processing blocked by routing policy.",
                "reason": route_decision.reason,
                "classification": route_decision.classification.value,
                "error_code": route_decision.error_code,
            },
        )

    job = await transformation_service.create_job(
        db,
        project_id=body.project_id,
        source_id=body.source_id,
        configuration_id=body.configuration_id,
        output_types=body.output_types,
        prompt=body.prompt,
        llm_provider=body.llm_provider,
        model=body.model,
    )
    # Enqueue the transformation job for asynchronous processing.
    try:
        enqueue_transformation_job(job.id, queue=get_transformation_queue())
    except Exception as exc:  # pragma: no cover - Redis availability edge
        logger.warning(
            "Transformation job could not be enqueued",
            job_id=str(job.id),
            error=str(exc),
        )
    # Also dispatch to in-process background worker so jobs are executed immediately
    # without depending on an external Redis worker daemon (e.g. single-service cloud deployments).
    background_tasks.add_task(execute_transformation_job_sync, str(job.id))

    metrics.inc("transformations_requested_total")
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


@transformations_router.get(
    "/{job_id}",
    response_model=TransformationJobDetailResponse,
    summary="Get a transformation job by ID",
)
async def get_transformation(
    job_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobDetailResponse:
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    # If the job is still queued (e.g. awaiting an external worker),
    # trigger immediate execution via background task so the client never hangs.
    if job.status == "queued":
        background_tasks.add_task(execute_transformation_job_sync, str(job.id))

    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


# ---------------------------------------------------------------------------
# Helpers for Job & Dissemination Resolution
# ---------------------------------------------------------------------------

async def _load_job(db: AsyncSession, job_id: uuid.UUID) -> Any:
    """Load a transformation job row (used to resolve scope/source)."""
    from app.db.models.transformation_job import TransformationJob
    from sqlalchemy import select

    result = await db.execute(select(TransformationJob).where(TransformationJob.id == job_id))
    return result.scalar_one_or_none()


async def _resolve_output_classification(db: AsyncSession, output: Any) -> Any:
    """Resolve the source/job classification for a given Output row."""
    from app.policy import DEFAULT_CLASSIFICATION, resolve_source_classification, normalize_classification
    if output.output_metadata and isinstance(output.output_metadata, dict):
        dissem = output.output_metadata.get("dissemination")
        if isinstance(dissem, dict) and dissem.get("classification"):
            try:
                return normalize_classification(dissem["classification"])
            except Exception:
                pass
    job = await _load_job(db, output.job_id)
    if job is not None:
        if job.source_id is not None:
            src = await source_service.get_source(db, source_id=job.source_id)
            if src is not None:
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


async def _ensure_output_dissemination(db: AsyncSession, output: Any) -> None:
    """Ensure output.output_metadata contains deterministic dissemination metadata."""
    if output.output_metadata and isinstance(output.output_metadata, dict):
        if "dissemination" in output.output_metadata:
            return
    try:
        classification = await _resolve_output_classification(db, output)
        from app.policy.dissemination import get_dissemination_engine
        engine = get_dissemination_engine()
        artifact_hash = None
        if output.output_metadata and isinstance(output.output_metadata, dict):
            integrity = output.output_metadata.get("integrity")
            if isinstance(integrity, dict):
                artifact_hash = integrity.get("hash") or integrity.get("content_digest")
        decisions = engine.evaluate_all(
            classification,
            output_type=output.output_type,
            artifact_hash=artifact_hash,
        )
        primary = engine.evaluate_output(
            classification,
            output_type=output.output_type,
            artifact_hash=artifact_hash,
        )
        payload = {
            "classification": classification.value,
            "policy_id": engine.POLICY_ID,
            "primary_destination": primary.destination,
            "primary_decision": primary.decision.value,
            "primary_allowed": primary.allowed,
            "primary_reason": primary.reason,
            "destinations": {
                k: {
                    "allowed": v.allowed,
                    "decision": v.decision.value,
                    "destination": v.destination,
                    "reason": v.reason,
                    "policy_id": v.policy_id,
                    "artifact_hash": v.artifact_hash,
                }
                for k, v in decisions.items()
            },
        }
        existing = dict(output.output_metadata or {})
        existing["dissemination"] = payload
        output.output_metadata = existing
    except Exception:
        pass


async def _ensure_output_provenance(db: AsyncSession, output: Any) -> None:
    """Ensure output.output_metadata contains canonical provenance metadata."""
    if output.output_metadata and isinstance(output.output_metadata, dict):
        if "provenance" in output.output_metadata:
            return
    try:
        from app.policy.provenance import ProvenanceBuilder
        from app.db.models.verification_result import VerificationResult
        from app.db.models.source import Source
        from sqlalchemy import select

        classification = await _resolve_output_classification(db, output)
        job = await _load_job(db, output.job_id)
        source = None
        if job and job.source_id:
            src_res = await db.execute(select(Source).where(Source.id == job.source_id))
            source = src_res.scalar_one_or_none()

        vr_res = await db.execute(
            select(VerificationResult)
            .where(VerificationResult.output_id == output.id)
            .order_by(VerificationResult.created_at.desc())
        )
        vr = vr_res.scalars().first()

        out_meta = dict(output.output_metadata or {})
        dissem_meta = out_meta.get("dissemination")
        integrity_meta = out_meta.get("integrity")
        resilience_meta = out_meta.get("resilience") or {}
        job_req_meta = dict(job.requested_outputs or {}) if job else {}
        citations = job_req_meta.get("evidence_citations")
        requested_types = list(job_req_meta.get("outputs", [])) or [output.output_type]

        record = ProvenanceBuilder.build_record(
            output_id=output.id,
            job_id=output.job_id,
            project_id=job.project_id if job else uuid.uuid4(),
            output_type=output.output_type,
            source=source,
            classification=str(classification.value if hasattr(classification, "value") else classification),
            requested_outputs=requested_types,
            prompt_provided=bool(job.prompt) if job else False,
            citations=citations,
            routing_metadata=resilience_meta,
            generator_class=out_meta.get("generator"),
            verification_result=vr,
            dissemination_metadata=dissem_meta,
            integrity_metadata=integrity_meta,
            is_backfill=(citations is None),
            audit_event_type="provenance_backfilled" if citations is None else "provenance_recorded",
        )

        approval_meta = out_meta.get("approval")
        if isinstance(approval_meta, dict):
            latest_aid = approval_meta.get("latest_approval_id")
            if latest_aid:
                record.extensions.approval_id = latest_aid

        out_meta["provenance"] = record.model_dump(mode="json")
        output.output_metadata = out_meta
    except Exception:
        pass


@transformations_router.get(
    "/{job_id}/outputs",
    response_model=OutputListResponse,
    summary="List outputs for a transformation job",
)
async def list_job_outputs(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputListResponse:
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    outputs = await transformation_service.list_job_outputs(db, job_id=job_id)
    for o in outputs:
        await _ensure_output_dissemination(db, o)
        await _ensure_output_provenance(db, o)
    return OutputListResponse(
        data=[OutputResponse.model_validate(o) for o in outputs],
        count=len(outputs),
    )


@transformations_router.post(
    "/{job_id}/cancel",
    response_model=TransformationJobDetailResponse,
    summary="Cancel a transformation job",
)
async def cancel_transformation(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> TransformationJobDetailResponse:
    """
    Cancel a transformation job and revoke any queued Redis task.

    Phase 6 performs real cancellation/revocation where supported by RQ and
    always marks the job cancelled in the database.
    """
    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )
    if job.status not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} cannot be cancelled (current status: {job.status}).",
        )
    from datetime import datetime, timezone

    # Revoke the queued Redis task if present (best-effort).
    try:
        cancel_transformation_job(job.id, queue=get_transformation_queue())
    except Exception as exc:  # pragma: no cover - Redis availability edge
        logger.warning(
            "Transformation job revocation failed",
            job_id=str(job_id),
            error=str(exc),
        )

    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(job)
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}",
    response_model=OutputDetailResponse,
    summary="Get an output by ID",
)
async def get_output(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputDetailResponse:
    # Authorization resolved at the database level:
    # Output → job → project → user.
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    await _ensure_output_dissemination(db, output)
    await _ensure_output_provenance(db, output)
    return OutputDetailResponse(data=OutputResponse.model_validate(output))


@outputs_router.get(
    "/{output_id}/verification",
    response_model=VerificationListResponse,
    summary="List verification results for an output",
)
async def list_output_verifications(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> VerificationListResponse:
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    verifications = await transformation_service.list_output_verifications(
        db, output_id=output_id
    )
    return VerificationListResponse(
        data=[VerificationResultResponse.model_validate(v) for v in verifications],
        count=len(verifications),
    )


@outputs_router.get(
    "/{output_id}/integrity",
    response_model=IntegrityDetailResponse,
    summary="Get the integrity/provenance record for an output artifact",
)
async def get_output_integrity(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> IntegrityDetailResponse:
    # Authorization is resolved at the database level (Output -> job -> project
    # -> user); a non-owned output is indistinguishable from a missing one.
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    meta = (output.output_metadata or {}).get("integrity")
    if not isinstance(meta, dict) or not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} has no integrity record.",
        )
    return IntegrityDetailResponse(
        data=IntegrityRecordResponse(
            output_id=output.id,
            digest=meta.get("digest"),
            algorithm=meta.get("algorithm"),
            representation=meta.get("representation"),
            provider=meta.get("provider"),
            reference=meta.get("reference"),
            status=meta.get("status", "unavailable"),
            recorded=bool(meta.get("recorded", False)),
            verified_at=meta.get("verified_at"),
        )
    )


@outputs_router.post(
    "/{output_id}/verify",
    response_model=IntegrityVerifyResponse,
    summary="Verify the current artifact against its recorded SHA-256 digest",
)
async def verify_output_integrity_endpoint(
    output_id: uuid.UUID,
    role: Literal["primary", "pdf", "srt"] = Query(default="primary"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> IntegrityVerifyResponse:
    from app.integrity.service import verify_output_integrity as _verify

    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    if output.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Output {output_id} is not in a completed state.",
        )
    result = _verify(output, storage=get_storage(), ledger=None, role=role)
    return IntegrityVerifyResponse(data=result)


@outputs_router.post(
    "/{output_id}/verify-facts",
    response_model=FactVerificationResponse,
    summary="Deterministically verify an output's factual claims against source evidence",
)
async def verify_output_facts_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FactVerificationResponse:
    """Run Phase 11N fact verification for one completed output.

    Extracts factual claims from the output, retrieves project-scoped source
    evidence via the provenance-carrying RAG path, and assigns a deterministic
    SUPPORTED / CONTRADICTED / UNVERIFIED verdict per claim. The report is
    persisted into the existing ``VerificationResult`` table. Purely additive —
    it never runs inside the generation workflow.
    """
    from app.services.transformation_service import (
        get_output_owned as _get_output_owned,
    )

    if not settings.FACT_VERIFICATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fact verification is disabled by configuration.",
        )

    output = await _get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    if output.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Output {output_id} is not in a completed state "
                "(facts can only be verified against a completed generation)."
            ),
        )

    job = await _load_job(db, output.job_id)
    if job is None or job.source_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Output {output_id} has no resolvable source to verify against.",
        )
    if job.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Output {output_id} has no resolvable project scope.",
        )

    from app.transformation.verification_engine import fact_verifier

    # Phase 11K audit lifecycle (started → completed | failed). These events are
    # fail-safe: an audit-sink failure can never change the verification outcome.
    fact_verifier.emit_audit_event(
        "fact_verification_started",
        outcome="started",
        user_id=str(current_user.id),
        project_id=str(job.project_id),
        source_id=str(job.source_id),
        job_id=str(job.id),
        output_id=str(output.id),
        reason="fact_verification_begin",
    )

    try:
        report, record_id = await db.run_sync(
            _run_fact_verification_sync,
            output=output,
            project_id=job.project_id,
            source_id=job.source_id,
        )
    except Exception:  # retrieval/persistence failure — surface without leaking details
        fact_verifier.emit_audit_event(
            "fact_verification_failed",
            outcome="failed",
            user_id=str(current_user.id),
            project_id=str(job.project_id),
            source_id=str(job.source_id),
            job_id=str(job.id),
            output_id=str(output.id),
            reason="evidence-retrieval-or-persistence-failed",
        )
        logger.warning(
            "fact_verification_failed",
            output_id=str(output_id),
            error="evidence-retrieval-or-persistence-failed",
        )
        metrics.inc("fact_verification_requests_total", {"result": "failed"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fact verification could not be completed for this output.",
        ) from None

    fact_verifier.emit_metrics(report)
    fact_verifier.emit_audit_event(
        "fact_verification_completed",
        outcome="completed",
        user_id=str(current_user.id),
        project_id=str(job.project_id),
        source_id=str(job.source_id),
        job_id=str(job.id),
        output_id=str(output.id),
        reason=report.overall_status,
        details={
            "overall_status": report.overall_status,
            "claims_checked": report.claims_checked,
            "claims_supported": report.claims_supported,
            "claims_contradicted": report.claims_contradicted,
            "claims_unverified": report.claims_unverified,
        },
    )
    return _build_fact_verification_response(report, record_id)


def _build_fact_verification_response(
    report: Any, record_id: uuid.UUID
) -> FactVerificationResponse:
    """Assemble the bounded response envelope from a completed report."""
    return FactVerificationResponse(
        data=FactVerificationResultResponse(
            report_id=record_id,
            output_id=report.output_id,
            overall_status=report.overall_status,
            summary=report.summary,
            claims_checked=report.claims_checked,
            claims_supported=report.claims_supported,
            claims_contradicted=report.claims_contradicted,
            claims_unverified=report.claims_unverified,
            claims=[
                FactVerificationClaimResponse(
                    id=check.claim_id,
                    text=check.text,
                    claim_type=check.claim_type,
                    verdict=check.verdict,
                    reason=check.reason,
                    overlap=check.overlap,
                    evidence=[
                        FactVerificationEvidenceResponse(
                            source_id=ev.citation.source_id,
                            chunk_id=ev.citation.chunk_id,
                            chunk_index=ev.citation.chunk_index,
                            evidence=ev.citation.evidence,
                            relevance_score=ev.citation.relevance_score,
                            overlap=ev.overlap,
                            numeric_conflict=ev.numeric_conflict,
                            date_conflict=ev.date_conflict,
                        )
                        for ev in check.evidence
                    ],
                )
                for check in report.claims
            ],
        )
    )


def _run_fact_verification_sync(
    sync_db: Any,
    *,
    output: Any,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
) -> tuple[Any, uuid.UUID]:
    """Run the sync Phase 11N pipeline + persistence against the session bridge."""
    from app.rag.service import RAGService
    from app.transformation.verification_engine import fact_verifier

    rag_service = RAGService()
    report = fact_verifier.verify_facts(
        output=output,
        rag_service=rag_service,
        db=sync_db,
        project_id=project_id,
        source_id=source_id,
    )
    record = fact_verifier.persist_report(sync_db, report)
    sync_db.commit()
    return report, record.id


# ---------------------------------------------------------------------------
# Trust Status + Cross-Output Consistency (Phase 12B)
# ---------------------------------------------------------------------------

@transformations_router.get(
    "/{job_id}/consistency",
    response_model=ConsistencyResponse,
    summary="Trust status + cross-output consistency for a transformation job",
)
async def get_job_consistency(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ConsistencyResponse:
    """Deterministic trust-status and cross-output consistency evaluation.

    Aggregates existing verification, security, integrity, and fact-verification
    signals into a per-output trust status (TRUSTED / CAUTION / UNVERIFIED) and
    checks completed outputs for numeric, percentage, and date conflicts.
    No LLM calls, no arbitrary scores — only explicit reason codes.
    """
    from app.transformation.verification_engine.cross_output import (
        check_cross_output_consistency,
    )
    from app.transformation.verification_engine.trust_status import (
        evaluate_trust_status,
    )

    job = await transformation_service.get_job(
        db, job_id=job_id, user_id=current_user.id
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )

    outputs = await transformation_service.list_job_outputs(db, job_id=job_id)

    # Build per-output trust statuses.
    trust_statuses: list[TrustStatusResponse] = []
    output_dicts: list[dict[str, Any]] = []

    for out in outputs:
        # Load verification results for this output.
        verifications = await transformation_service.list_output_verifications(
            db, output_id=out.id
        )
        vr_dicts = [
            {
                "overall_status": v.overall_status,
                "grounding_score": v.grounding_score,
                "consistency_score": v.consistency_score,
                "claims_checked": v.claims_checked,
                "claims_supported": v.claims_supported,
                "warnings": v.warnings,
                "details": v.details,
            }
            for v in verifications
        ]

        trust = evaluate_trust_status(
            output_id=str(out.id),
            output_type=out.output_type,
            output_status=out.status,
            output_metadata=out.output_metadata,
            verification_results=vr_dicts,
        )
        trust_statuses.append(
            TrustStatusResponse(
                status=trust.status,
                reason_codes=trust.reason_codes,
                signals=[
                    TrustSignalResponse(
                        category=s.category,
                        present=s.present,
                        status=s.status,
                        reason_code=s.reason_code,
                        detail=s.detail,
                    )
                    for s in trust.signals
                ],
                output_id=trust.output_id,
                output_type=trust.output_type,
            )
        )

        output_dicts.append(
            {
                "id": str(out.id),
                "output_type": out.output_type,
                "status": out.status,
                "text_content": out.text_content,
                "structured_content": out.structured_content,
            }
        )

    # Cross-output consistency check.
    cross = check_cross_output_consistency(output_dicts)
    cross_response = CrossOutputConsistencyResponse(
        status=cross.status,
        completed_output_count=cross.completed_output_count,
        conflicts=[
            ConsistencyConflictResponse(
                category=conflict.category,
                value_a=conflict.value_a,
                value_b=conflict.value_b,
                output_a_id=conflict.output_a_id,
                output_a_type=conflict.output_a_type,
                output_b_id=conflict.output_b_id,
                output_b_type=conflict.output_b_type,
                message=conflict.message,
            )
            for conflict in cross.conflicts
        ],
        checked_pairs=cross.checked_pairs,
        note=cross.note,
    )

    return ConsistencyResponse(
        data=ConsistencyResultResponse(
            job_id=job.id,
            trust_statuses=trust_statuses,
            cross_output=cross_response,
        )
    )


@outputs_router.post(
    "/{output_id}/export",
    response_class=Response,
    summary="Export a text output to DOCX or PDF",
)
async def export_output_document(
    output_id: uuid.UUID,
    format: Literal["docx", "pdf"] = Query(default="pdf"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    """
    Render a completed text output (Executive Summary / Advisory) into DOCX or
    PDF and stream it to the owning user.

    The export is generated statelessly from the output's stored structured
    content — no storage write and no new secrets.  Binary outputs
    (presentation / infographic / video) keep their existing artifact download
    path via GET /outputs/{id}/download.
    """
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    if output.output_type not in ("summary", "advisory"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Export to {format} is not supported for output type "
                f"{output.output_type!r}. Use the artifact download for "
                "presentation, infographic and video outputs."
            ),
        )
    if output.status != "completed":
        if output.status == "generating":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Output {output_id} is still generating.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} has no exportable content.",
        )

    # Phase 2D: Dissemination Policy Enforcement for DOWNLOAD destination
    classification = await _resolve_output_classification(db, output)
    from app.policy.dissemination import DisseminationDestination, get_dissemination_engine
    engine = get_dissemination_engine()
    dissem_decision = engine.evaluate(
        classification=classification,
        destination=DisseminationDestination.DOWNLOAD,
        output_type=output.output_type,
    )
    if not dissem_decision.allowed:
        from app.core.audit import emit_security_event
        emit_security_event(
            "dissemination_blocked",
            outcome="blocked",
            user_id=str(current_user.id),
            reason=dissem_decision.reason,
            details={
                "output_id": str(output.id),
                "destination": DisseminationDestination.DOWNLOAD.value,
                "classification": dissem_decision.classification.value,
                "output_type": output.output_type,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Dissemination blocked by policy.",
                "reason": dissem_decision.reason,
                "destination": DisseminationDestination.DOWNLOAD.value,
                "classification": dissem_decision.classification.value,
                "decision": dissem_decision.decision.value,
            },
        )

    # Phase 2F: Approval Verification for DOWNLOAD destination
    eligible, release_reason = await approval_service.verify_release_eligibility(
        db,
        output=output,
        destination=DisseminationDestination.DOWNLOAD,
        user_id=current_user.id,
    )
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Export blocked by approval policy.",
                "reason": release_reason,
                "destination": DisseminationDestination.DOWNLOAD.value,
            },
        )

    structured = output.structured_content
    if not structured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} has no exportable content.",
        )
    try:
        if output.output_type == "summary":
            model = ExecutiveSummary.model_validate(structured)
            bytes = (
                render_executive_summary_docx(model)
                if format == "docx"
                else render_executive_summary_pdf(model)
            )
            mime_type = DOCX_MIME_TYPE if format == "docx" else PDF_MIME_TYPE
        else:
            model = Advisory.model_validate(structured)
            bytes = (
                render_advisory_docx(model)
                if format == "docx"
                else render_advisory_pdf(model)
            )
            mime_type = DOCX_MIME_TYPE if format == "docx" else PDF_MIME_TYPE
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The stored output content is not in a supported exportable format.",
        ) from None
    filename = f"{output.output_type}.{format}"
    return Response(
        content=bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@outputs_router.get(
    "/{output_id}/download",
    response_class=Response,
    summary="Download an output artifact",
)
async def download_output_artifact(
    output_id: uuid.UUID,
    artifact: Literal["primary", "pdf", "srt"] = Query(default="primary"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    """
    Stream a generated artifact's bytes to the owning user.

    The artifact role is limited to ``primary`` (the output's own file) plus the
    companion roles persisted in ``output_metadata`` (``pdf`` for the
    infographic's PDF sibling, ``srt`` for the video package's subtitles).  The
    storage key is resolved server-side from the authorized Output record — the
    client never supplies a storage key.
    """
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    if output.status != "completed":
        if output.status == "generating":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Output {output_id} is still generating.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} has no downloadable artifact.",
        )

    # Phase 2D: Dissemination Policy Enforcement for DOWNLOAD destination
    classification = await _resolve_output_classification(db, output)
    from app.policy.dissemination import DisseminationDestination, get_dissemination_engine
    engine = get_dissemination_engine()
    dissem_decision = engine.evaluate(
        classification=classification,
        destination=DisseminationDestination.DOWNLOAD,
        output_type=output.output_type,
    )
    if not dissem_decision.allowed:
        from app.core.audit import emit_security_event
        emit_security_event(
            "dissemination_blocked",
            outcome="blocked",
            user_id=str(current_user.id),
            reason=dissem_decision.reason,
            details={
                "output_id": str(output.id),
                "destination": DisseminationDestination.DOWNLOAD.value,
                "classification": dissem_decision.classification.value,
                "output_type": output.output_type,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Dissemination blocked by policy.",
                "reason": dissem_decision.reason,
                "destination": DisseminationDestination.DOWNLOAD.value,
                "classification": dissem_decision.classification.value,
                "decision": dissem_decision.decision.value,
            },
        )

    # Phase 2F: Approval Verification for DOWNLOAD destination
    eligible, release_reason = await approval_service.verify_release_eligibility(
        db,
        output=output,
        destination=DisseminationDestination.DOWNLOAD,
        user_id=current_user.id,
    )
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Download blocked by approval policy.",
                "reason": release_reason,
                "destination": DisseminationDestination.DOWNLOAD.value,
            },
        )

    resolved = artifact_file(output, artifact)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not available for output {output_id}.",
        )
    try:
        content = get_storage().read(resolved.storage_key)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not available for output {output_id}.",
        ) from None
    return Response(
        content=content,
        media_type=resolved.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{resolved.filename}"'},
    )


# ---------------------------------------------------------------------------
# Dissemination Endpoints (Phase 2D)
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}/dissemination",
    response_model=DisseminationReportResponse,
    summary="Get dissemination policy evaluation for an output across destinations",
)
async def get_output_dissemination_endpoint(
    output_id: uuid.UUID,
    destination: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DisseminationReportResponse:
    """Return deterministic dissemination decisions for an authorized output."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    classification = await _resolve_output_classification(db, output)
    from app.policy.dissemination import get_dissemination_engine
    engine = get_dissemination_engine()

    artifact_hash = None
    if output.output_metadata and isinstance(output.output_metadata, dict):
        integrity = output.output_metadata.get("integrity")
        if isinstance(integrity, dict):
            artifact_hash = integrity.get("hash") or integrity.get("content_digest")

    if destination:
        dec = engine.evaluate(
            classification=classification,
            destination=destination,
            output_type=output.output_type,
            artifact_hash=artifact_hash,
        )
        dest_dict = {
            dec.destination: DisseminationDecisionResponse(
                allowed=dec.allowed,
                decision=dec.decision.value,
                classification=dec.classification.value,
                destination=dec.destination,
                reason=dec.reason,
                policy_id=dec.policy_id,
                artifact_hash=dec.artifact_hash,
                signature=dec.signature,
                provenance_id=dec.provenance_id,
                approval_id=dec.approval_id,
                details=dec.details,
            )
        }
    else:
        all_decs = engine.evaluate_all(
            classification=classification,
            output_type=output.output_type,
            artifact_hash=artifact_hash,
        )
        dest_dict = {
            d_name: DisseminationDecisionResponse(
                allowed=d.allowed,
                decision=d.decision.value,
                classification=d.classification.value,
                destination=d.destination,
                reason=d.reason,
                policy_id=d.policy_id,
                artifact_hash=d.artifact_hash,
                signature=d.signature,
                provenance_id=d.provenance_id,
                approval_id=d.approval_id,
                details=d.details,
            )
            for d_name, d in all_decs.items()
        }

    return DisseminationReportResponse(
        success=True,
        output_id=output.id,
        output_type=output.output_type,
        classification=classification.value,
        destinations=dest_dict,
    )


@outputs_router.post(
    "/{output_id}/disseminate",
    response_model=DisseminateResponse,
    summary="Attempt dissemination of an output to a target destination",
)
async def disseminate_output_endpoint(
    output_id: uuid.UUID,
    body: DisseminateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> DisseminateResponse:
    """Authoritatively evaluate dissemination to a destination and enforce policy."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    if output.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Output {output_id} is not in completed state (cannot disseminate).",
        )

    classification = await _resolve_output_classification(db, output)
    from app.policy.dissemination import get_dissemination_engine
    engine = get_dissemination_engine()

    artifact_hash = None
    if output.output_metadata and isinstance(output.output_metadata, dict):
        integrity = output.output_metadata.get("integrity")
        if isinstance(integrity, dict):
            artifact_hash = integrity.get("hash") or integrity.get("content_digest")

    decision = engine.evaluate(
        classification=classification,
        destination=body.destination,
        output_type=output.output_type,
        artifact_hash=artifact_hash,
    )

    from app.core.audit import emit_security_event
    emit_security_event(
        "dissemination_requested",
        outcome="allowed" if decision.allowed else "blocked",
        user_id=str(current_user.id),
        reason=decision.reason,
        details={
            "output_id": str(output.id),
            "destination": decision.destination,
            "classification": decision.classification.value,
            "output_type": output.output_type,
            "decision": decision.decision.value,
        },
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Dissemination blocked by policy.",
                "reason": decision.reason,
                "destination": decision.destination,
                "classification": decision.classification.value,
                "decision": decision.decision.value,
            },
        )

    # Phase 2F: Approval Verification for requested destination
    eligible, release_reason = await approval_service.verify_release_eligibility(
        db,
        output=output,
        destination=body.destination,
        user_id=current_user.id,
    )
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Dissemination blocked by approval policy.",
                "reason": release_reason,
                "destination": decision.destination,
                "classification": decision.classification.value,
                "decision": decision.decision.value,
            },
        )

    # Fetch approval_id if present for this destination
    appr_meta = (output.output_metadata or {}).get("approval", {})
    dest_appr = appr_meta.get("destinations", {}).get(decision.destination, {})
    resolved_approval_id = dest_appr.get("approval_id") or appr_meta.get("latest_approval_id") or decision.approval_id

    resp_data = DisseminationDecisionResponse(
        allowed=decision.allowed,
        decision=decision.decision.value,
        classification=decision.classification.value,
        destination=decision.destination,
        reason=decision.reason,
        policy_id=decision.policy_id,
        artifact_hash=decision.artifact_hash,
        signature=decision.signature,
        provenance_id=decision.provenance_id,
        approval_id=resolved_approval_id,
        details=decision.details,
    )
    return DisseminateResponse(success=True, data=resp_data)


@transformations_router.post(
    "/dissemination/evaluate",
    response_model=DisseminateResponse,
    summary="Evaluate dissemination policy without an existing output",
)
async def evaluate_dissemination_policy_endpoint(
    body: DisseminationEvaluateRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> DisseminateResponse:
    """Pre-evaluate dissemination policy for a classification and destination."""
    from app.policy.dissemination import get_dissemination_engine
    engine = get_dissemination_engine()
    decision = engine.evaluate(
        classification=body.classification,
        destination=body.destination,
        output_type=body.output_type,
    )
    resp_data = DisseminationDecisionResponse(
        allowed=decision.allowed,
        decision=decision.decision.value,
        classification=decision.classification.value,
        destination=decision.destination,
        reason=decision.reason,
        policy_id=decision.policy_id,
        artifact_hash=decision.artifact_hash,
        signature=decision.signature,
        provenance_id=decision.provenance_id,
        approval_id=decision.approval_id,
        details=decision.details,
    )
    return DisseminateResponse(success=True, data=resp_data)


# ---------------------------------------------------------------------------
# Provenance Endpoints (Phase 2E)
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}/provenance",
    response_model=ProvenanceDetailResponse,
    summary="Get canonical provenance record for an output",
)
async def get_output_provenance_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ProvenanceDetailResponse:
    """Return deterministic, auditable provenance lineage for an authorized output."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    await _ensure_output_dissemination(db, output)
    await _ensure_output_provenance(db, output)

    prov_data = (output.output_metadata or {}).get("provenance")
    if not prov_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provenance record for output {output_id} is unavailable.",
        )

    return ProvenanceDetailResponse(
        success=True,
        output_id=output.id,
        data=prov_data,
    )


# ---------------------------------------------------------------------------
# Human Approval & Controlled Release Endpoints (Phase 2F)
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}/approval",
    response_model=ApprovalStatusResponse,
    summary="Get approval status for an output across destinations (Phase 2F)",
)
async def get_output_approval_endpoint(
    output_id: uuid.UUID,
    destination: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApprovalStatusResponse:
    """Return destination-scoped human approval status for an authorized output."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )
    classification = await approval_service.resolve_output_classification(db, output)
    meta = await approval_service.get_or_initialize_output_approval(db, output)

    if destination:
        from app.policy.dissemination import normalize_destination
        try:
            norm_dest = normalize_destination(destination).value
            dests = {norm_dest: meta.destinations[norm_dest]} if norm_dest in meta.destinations else {}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from None
    else:
        dests = meta.destinations

    return ApprovalStatusResponse(
        success=True,
        output_id=output.id,
        classification=classification.value,
        destinations={
            k: DestinationApprovalDetail(
                destination=v.destination,
                approval_status=v.approval_status,
                approval_id=v.approval_id,
                decision=v.decision,
                approver_id=v.approver_id,
                approver_email=v.approver_email,
                approver_role=v.approver_role,
                approved_at=v.approved_at,
                rejection_reason=v.rejection_reason,
                comments=v.comments,
                self_approved=v.self_approved,
                policy_reason=v.policy_reason,
                classification_snapshot=v.classification_snapshot,
                verification_status_snapshot=v.verification_status_snapshot,
            )
            for k, v in dests.items()
        },
        latest_approval_id=meta.latest_approval_id,
    )


@outputs_router.post(
    "/{output_id}/approval",
    response_model=ApprovalActionResponse,
    summary="Submit an approval or rejection decision for a destination (Phase 2F)",
)
async def submit_output_approval_endpoint(
    output_id: uuid.UUID,
    body: ApprovalActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApprovalActionResponse:
    """Authoritatively record a human approval or rejection decision for an output destination."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )

    rec = await approval_service.submit_output_approval(
        db,
        output=output,
        current_user=current_user,
        destination=body.destination,
        action=body.action,
        comments=body.comments,
        rejection_reason=body.rejection_reason,
    )

    return ApprovalActionResponse(
        success=True,
        data=DestinationApprovalDetail(
            destination=rec.destination,
            approval_status=rec.approval_status,
            approval_id=rec.approval_id,
            decision=rec.decision,
            approver_id=rec.approver_id,
            approver_email=rec.approver_email,
            approver_role=rec.approver_role,
            approved_at=rec.approved_at,
            rejection_reason=rec.rejection_reason,
            comments=rec.comments,
            self_approved=rec.self_approved,
            policy_reason=rec.policy_reason,
            classification_snapshot=rec.classification_snapshot,
            verification_status_snapshot=rec.verification_status_snapshot,
        ),
    )


# ---------------------------------------------------------------------------
# Cryptographic Integrity Endpoints (Phase 2G)
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}/integrity",
    response_model=OutputIntegrityResponse,
    summary="Get cryptographic integrity status and digests for an output (Phase 2G)",
)
async def get_output_integrity_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputIntegrityResponse:
    """Return authoritative cryptographic integrity record for an authorized output."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )

    meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    stored = meta.get("cryptographic_integrity")
    if not isinstance(stored, dict):
        detail = OutputIntegrityDetail(
            status="UNAVAILABLE",
            algorithm="sha256",
            artifact_hash=None,
            companion_hashes={},
            provenance_id=None,
            provenance_hash=None,
            approval_id=None,
            recorded_at=None,
            details={"reason": "Cryptographic integrity record not found (legacy or unsealed output)."},
        )
    else:
        detail = OutputIntegrityDetail(
            status=stored.get("status", "VERIFIED"),
            algorithm=stored.get("algorithm", "sha256"),
            artifact_hash=stored.get("artifact_hash"),
            companion_hashes=stored.get("companion_hashes", {}),
            provenance_id=stored.get("provenance_id"),
            provenance_hash=stored.get("provenance_hash"),
            approval_id=stored.get("approval_id"),
            recorded_at=stored.get("recorded_at"),
            details={},
        )

    return OutputIntegrityResponse(
        success=True,
        output_id=output.id,
        data=detail,
    )


@outputs_router.post(
    "/{output_id}/integrity/verify",
    response_model=IntegrityVerifyResponse,
    summary="Verify cryptographic integrity of output artifacts and provenance (Phase 2G)",
)
async def verify_output_integrity_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> IntegrityVerifyResponse:
    """Verify current output artifact bytes and provenance against the stored cryptographic integrity record."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )

    res = integrity_service.verify_output_integrity(output)
    return IntegrityVerifyResponse(
        success=True,
        output_id=output.id,
        data=OutputIntegrityDetail(
            status=res["status"],
            algorithm=res.get("algorithm", "sha256"),
            artifact_hash=res.get("artifact_hash"),
            companion_hashes=res.get("companion_hashes", {}),
            provenance_id=res.get("provenance_id"),
            provenance_hash=res.get("provenance_hash"),
            approval_id=res.get("approval_id"),
            recorded_at=res.get("recorded_at"),
            details=res.get("details", {}),
        ),
    )


# ---------------------------------------------------------------------------
# Digital Signature Endpoints (Phase 2H)
# ---------------------------------------------------------------------------

@outputs_router.get(
    "/{output_id}/signature",
    response_model=OutputSignatureResponse,
    summary="Get digital signature status and verification metadata for an output (Phase 2H)",
)
async def get_output_signature_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> OutputSignatureResponse:
    """Return authoritative digital signature record for an authorized output."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )

    meta = output.output_metadata if isinstance(output.output_metadata, dict) else {}
    stored = meta.get("digital_signature")
    if not isinstance(stored, dict):
        detail = OutputSignatureDetail(
            status="UNAVAILABLE",
            algorithm=None,
            key_id=None,
            signature=None,
            signed_payload_hash=None,
            signed_integrity_hash=None,
            signed_provenance_hash=None,
            signed_at=None,
            provider=None,
            details={"reason": "Digital signature record not found (legacy or unsigned output)."},
        )
    else:
        detail = OutputSignatureDetail(
            status=stored.get("status", "VALID"),
            algorithm=stored.get("algorithm"),
            key_id=stored.get("key_id"),
            signature=stored.get("signature"),
            signed_payload_hash=stored.get("signed_payload_hash"),
            signed_integrity_hash=stored.get("signed_integrity_hash"),
            signed_provenance_hash=stored.get("signed_provenance_hash"),
            signed_at=stored.get("signed_at"),
            provider=stored.get("provider"),
            details={},
        )

    return OutputSignatureResponse(
        success=True,
        output_id=output.id,
        data=detail,
    )


@outputs_router.post(
    "/{output_id}/signature/verify",
    response_model=SignatureVerifyResponse,
    summary="Verify digital signature and underlying cryptographic integrity for an output (Phase 2H)",
)
async def verify_output_signature_endpoint(
    output_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> SignatureVerifyResponse:
    """Verify cryptographic signature and underlying integrity against authoritative output state."""
    output = await transformation_service.get_output_owned(
        db, output_id=output_id, user_id=current_user.id
    )
    if output is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output {output_id} not found.",
        )

    res = signature_service.verify_output_signature(output)
    return SignatureVerifyResponse(
        success=True,
        output_id=output.id,
        data=OutputSignatureDetail(
            status=res["status"],
            algorithm=res.get("algorithm"),
            key_id=res.get("key_id"),
            signature=res.get("signature"),
            signed_payload_hash=res.get("signed_payload_hash"),
            signed_integrity_hash=res.get("signed_integrity_hash"),
            signed_provenance_hash=res.get("signed_provenance_hash"),
            signed_at=res.get("signed_at"),
            provider=res.get("provider"),
            details=res.get("details", {}),
        ),
    )
