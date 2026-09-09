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
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
)
from app.core.ratelimit import rate_limit_bucket
from app.core.config import settings
from app.db.session import get_db
from app.core.metrics import metrics
from app.services import project_service, source_service, configuration_service, transformation_service
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
    job = await transformation_service.create_job(
        db,
        project_id=body.project_id,
        source_id=body.source_id,
        configuration_id=body.configuration_id,
        output_types=body.output_types,
        prompt=body.prompt,
    )
    # Enqueue the transformation job for asynchronous processing. Enqueueing is
    # best-effort: if Redis is unavailable the job record still persists in the
    # queued state so callers can observe/retry it (resilience, not corruption).
    try:
        enqueue_transformation_job(job.id, queue=get_transformation_queue())
    except Exception as exc:  # pragma: no cover - Redis availability edge
        logger.warning(
            "Transformation job could not be enqueued",
            job_id=str(job.id),
            error=str(exc),
        )
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
    return TransformationJobDetailResponse(
        data=TransformationJobResponse.model_validate(job)
    )


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


async def _load_job(db: AsyncSession, job_id: uuid.UUID) -> Any:
    """Load a transformation job row (used to resolve scope/source)."""
    from app.db.models.transformation_job import TransformationJob

    from sqlalchemy import select

    result = await db.execute(select(TransformationJob).where(TransformationJob.id == job_id))
    return result.scalar_one_or_none()


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
