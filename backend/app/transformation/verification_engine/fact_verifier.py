"""Phase 11N — evidence-based fact verification for generated outputs.

A focused, on-demand fact-verification layer that sits *alongside* the Phase 8
verification pipeline (never inside the generation workflow). For each checkable
claim extracted from a completed output, it retrieves project-scoped source
evidence through the existing provenance-carrying RAG path
(``RAGService.retrieve_context_for_source`` → ``RAGCitation``) and then applies
the same deterministic lexical-overlap + numeric/date conflict logic proven in
``evidence.py`` to assign a three-state verdict:

    SUPPORTED      — a retrieved chunk overlaps the claim strongly (>= 0.55)
                     with no numeric/date conflict.
    CONTRADICTED   — the closest retrieved chunk overlaps the claim and its
                     numbers or dates conflict with the claim's values.
    UNVERIFIED     — no overlapping evidence was retrieved (weak, ambiguous,
                     or absent evidence).

This is deliberately *not* a claim of ground-truth factual correctness. It only
reports whether a claim is supported by the project's own source material. The
pipeline is deterministic and runs fully offline (no API key, no provider, no
network), matching the Phase 8 design.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core import audit
from app.core.config import settings
from app.core.metrics import metrics
from app.db.models.output import Output
from app.db.models.verification_result import VerificationResult
from app.rag.schemas import RAGCitation
from app.rag.service import RAGService
from app.transformation.verification_engine.claims import extract_claims
from app.transformation.verification_engine.evidence import (
    _STRONG_OVERLAP,
    _excerpt,
)

# Verdicts (stable public API values).
VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_CONTRADICTED = "CONTRADICTED"
VERDICT_UNVERIFIED = "UNVERIFIED"

# Marker persisted in VerificationResult.details.generator so consumers can
# distinguish a Phase 11N report from a Phase 8 report.
GENERATOR = "deterministic-phase11n-factcheck"

STATUS_PASSED = "passed"
STATUS_WARNING = "warning"
STATUS_FAILED = "failed"

logger = structlog.get_logger(__name__)


@dataclass
class ClaimEvidence:
    """Retrieved, provenance-carrying evidence for a single claim."""

    citation: RAGCitation
    overlap: float
    numeric_conflict: bool
    date_conflict: bool


@dataclass
class ClaimFactCheck:
    """The deterministic outcome for one extracted claim."""

    claim_id: str
    text: str
    claim_type: str
    verdict: str
    reason: str
    overlap: float = 0.0
    evidence: list[ClaimEvidence] = field(default_factory=list)


@dataclass
class FactVerificationReport:
    """Assembled, bounded fact-verification result safe for persistence."""

    output_id: uuid.UUID
    overall_status: str
    summary: str
    claims_checked: int
    claims_supported: int
    claims_contradicted: int
    claims_unverified: int
    claims: list[ClaimFactCheck]

    @property
    def result_id(self) -> uuid.UUID:
        return uuid.uuid4()


def _claim_excerpt(text: str, limit: int = 240) -> str:
    """Cap a claim so persisted/serialized text stays bounded."""
    return _excerpt(text, limit)


def _resolve_top_k(top_k: int | None) -> int:
    if top_k is None:
        return int(settings.FACT_VERIFICATION_TOP_K)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be a positive integer.")
    return top_k


def _resolve_max_evidence(max_evidence: int | None) -> int:
    if max_evidence is None:
        return int(settings.FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM)
    if not isinstance(max_evidence, int) or isinstance(max_evidence, bool) or max_evidence <= 0:
        raise ValueError("max_evidence must be a positive integer.")
    return max_evidence


def retrieve_claim_evidence(
    rag_service: RAGService,
    db: Any,
    *,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    claim_text: str,
    top_k: int,
) -> list[RAGCitation]:
    """Retrieve project-scoped source citations for one claim via RAG."""
    context = rag_service.retrieve_context_for_source(
        db,
        source_id=source_id,
        query=claim_text,
        project_id=project_id,
        top_k=top_k,
        task_context="fact-verification",
        min_similarity=float(settings.FACT_VERIFICATION_MIN_SIMILARITY),
    )
    return list(context.citations)


def _conflicts(citation: RAGCitation, claim: dict[str, Any]) -> tuple[float, bool, bool]:
    """Return (overlap, numeric_conflict, date_conflict) for a claim vs one citation."""
    from app.transformation.verification_engine.text_utils import (
        extract_dates,
        extract_numbers,
        meaningful_terms,
    )

    claim_terms = meaningful_terms(claim["text"])
    chunk_terms = meaningful_terms(citation.evidence)
    overlap = (
        len(claim_terms & chunk_terms) / len(claim_terms)
        if claim_terms
        else 0.0
    )

    claim_numbers = set(claim["numbers"])
    chunk_numbers = set(extract_numbers(citation.evidence))
    numeric_conflict = bool(claim_numbers) and bool(chunk_numbers) and not claim_numbers.issubset(
        chunk_numbers
    )

    claim_dates = set(claim["dates"])
    chunk_dates = set(extract_dates(citation.evidence))
    date_conflict = bool(claim_dates) and bool(chunk_dates) and not claim_dates.issubset(
        chunk_dates
    )

    return overlap, numeric_conflict, date_conflict


def _rank_evidence(
    evidences: list[ClaimEvidence], max_evidence: int
) -> list[ClaimEvidence]:
    """Deterministically order evidence: strongest overlap first, ties by chunk."""
    ordered = sorted(
        evidences,
        key=lambda e: (e.overlap, -e.citation.chunk_index),
        reverse=True,
    )
    return ordered[:max_evidence]


def check_claim(
    claim: dict[str, Any],
    citations: list[RAGCitation],
    *,
    max_evidence: int,
) -> ClaimFactCheck:
    """Deterministically assign a three-state verdict to one claim.

    Mirrors ``evidence.analyze_claim``: a numeric/date conflict on the closest
    overlapping chunk outranks weak lexical support, so an altered figure is
    always surfaced as CONTRADICTED rather than UNVERIFIED/SUPPORTED.
    """
    from app.transformation.verification_engine.text_utils import meaningful_terms

    claim_terms = meaningful_terms(claim["text"])

    candidate: ClaimEvidence | None = None
    all_evidences: list[ClaimEvidence] = []

    for citation in citations:
        overlap, numeric_conflict, date_conflict = _conflicts(citation, claim)
        evidence = ClaimEvidence(
            citation=citation,
            overlap=overlap,
            numeric_conflict=numeric_conflict,
            date_conflict=date_conflict,
        )
        all_evidences.append(evidence)

        if claim_terms and overlap >= _STRONG_OVERLAP:
            if candidate is None or overlap > candidate.overlap:
                candidate = evidence

    ranked = _rank_evidence(all_evidences, max_evidence)

    if candidate is None:
        return ClaimFactCheck(
            claim_id=claim["id"],
            text=_claim_excerpt(claim["text"]),
            claim_type=claim["claim_type"],
            verdict=VERDICT_UNVERIFIED,
            reason="No retrieved source evidence overlaps this claim strongly.",
            overlap=0.0,
            evidence=ranked,
        )

    conflict = candidate.numeric_conflict or candidate.date_conflict
    if conflict:
        detail: list[str] = []
        if candidate.numeric_conflict:
            detail.append(
                "numbers in the claim do not match the source evidence"
            )
        if candidate.date_conflict:
            detail.append("dates in the claim do not match the source evidence")
        reason = f"Contradicted by source evidence ({' and '.join(detail)})."
    else:
        reason = (
            f"Supported by source evidence "
            f"(overlap {int(candidate.overlap * 100)}%)."
        )

    return ClaimFactCheck(
        claim_id=claim["id"],
        text=_claim_excerpt(claim["text"]),
        claim_type=claim["claim_type"],
        verdict=VERDICT_SUPPORTED if not conflict else VERDICT_CONTRADICTED,
        reason=reason,
        overlap=candidate.overlap,
        evidence=ranked,
    )


def _overall_status(
    claims_checked: int,
    supported: int,
    contradicted: int,
    unverified: int,
) -> tuple[str, str]:
    """Map per-claim outcomes to a report-level status + summary message."""
    if claims_checked == 0:
        return STATUS_PASSED, "No checkable factual claims were found in the output."
    if contradicted > 0:
        return (
            STATUS_FAILED,
            f"{contradicted} claim(s) contradicted by source evidence.",
        )
    if unverified > 0:
        return (
            STATUS_WARNING,
            f"{supported} of {claims_checked} claim(s) supported; "
            f"{unverified} unverified against source evidence.",
        )
    return (
        STATUS_PASSED,
        f"All {claims_checked} claim(s) supported by source evidence.",
    )


def verify_facts(
    *,
    output: Output,
    rag_service: RAGService,
    db: Any,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    equity: dict[str, Any] | None = None,
) -> FactVerificationReport:
    """Run the full Phase 11N fact-verification pipeline for one output.

    The pipeline is deterministic and DB-agnostic over the synchronous session
    bridge help by ``db`` (callers pass the same session they persist through,
    so retrieval and persistence share one transaction-safe session).
    """
    output_dict = output.structured_content or {"type": output.output_type}
    if isinstance(output_dict, str):
        output_dict = {"type": output.output_type, "text": output_dict}

    claims = extract_claims(output_dict, equity)
    max_claims = int(settings.FACT_VERIFICATION_MAX_CLAIMS)
    if max_claims > 0:
        claims = claims[:max_claims]

    top_k = _resolve_top_k(int(settings.FACT_VERIFICATION_TOP_K))
    max_evidence = _resolve_max_evidence(
        int(settings.FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM)
    )

    checks: list[ClaimFactCheck] = []
    for claim in claims:
        citations = retrieve_claim_evidence(
            rag_service,
            db,
            project_id=project_id,
            source_id=source_id,
            claim_text=claim["text"],
            top_k=top_k,
        )
        checks.append(check_claim(claim, citations, max_evidence=max_evidence))

    supported = sum(1 for c in checks if c.verdict == VERDICT_SUPPORTED)
    contradicted = sum(1 for c in checks if c.verdict == VERDICT_CONTRADICTED)
    unverified = sum(1 for c in checks if c.verdict == VERDICT_UNVERIFIED)
    overall_status, summary = _overall_status(
        len(checks), supported, contradicted, unverified
    )

    return FactVerificationReport(
        output_id=output.id,
        overall_status=overall_status,
        summary=summary,
        claims_checked=len(checks),
        claims_supported=supported,
        claims_contradicted=contradicted,
        claims_unverified=unverified,
        claims=checks,
    )


def persist_report(
    db: Any,
    report: FactVerificationReport,
) -> VerificationResult:
    """Persist a report into the existing ``VerificationResult`` table."""
    claims_data: list[dict[str, Any]] = []
    for check in report.claims:
        citation_data = [
            {
                "source_id": ev.citation.source_id,
                "chunk_id": ev.citation.chunk_id,
                "chunk_index": ev.citation.chunk_index,
                "evidence": _excerpt(ev.citation.evidence, 300),
                "relevance_score": ev.citation.relevance_score,
                "overlap": round(ev.overlap, 4),
                "numeric_conflict": ev.numeric_conflict,
                "date_conflict": ev.date_conflict,
            }
            for ev in check.evidence
        ]
        claims_data.append(
            {
                "id": check.claim_id,
                "text": check.text,
                "claim_type": check.claim_type,
                "verdict": check.verdict,
                "reason": check.reason,
                "overlap": round(check.overlap, 4),
                "evidence_count": len(citation_data),
                "evidence": citation_data,
            }
        )

    grounding_score = (
        round(report.claims_supported / report.claims_checked, 4)
        if report.claims_checked
        else None
    )

    record = VerificationResult(
        id=report.result_id,
        output_id=report.output_id,
        overall_status=report.overall_status,
        grounding_score=grounding_score,
        consistency_score=None,
        claims_checked=report.claims_checked,
        claims_supported=report.claims_supported,
        warnings={
            "status": report.overall_status,
            "message": report.summary,
            "items": [
                {
                    "type": "fact_verification",
                    "severity": (
                        "error"
                        if report.overall_status == STATUS_FAILED
                        else "warning"
                        if report.overall_status == STATUS_WARNING
                        else "info"
                    ),
                    "message": check.reason,
                    "claim_text": check.text,
                    "verdict": check.verdict,
                    "chunk_index": (
                        check.evidence[0].citation.chunk_index
                        if check.evidence
                        else None
                    ),
                }
                for check in report.claims
                if check.verdict != VERDICT_SUPPORTED
            ],
            "count": sum(
                1 for c in report.claims if c.verdict != VERDICT_SUPPORTED
            ),
        },
        details={
            "status": "completed",
            "generator": GENERATOR,
            "summary": report.summary,
            "claims_checked": report.claims_checked,
            "claims_supported": report.claims_supported,
            "claims_contradicted": report.claims_contradicted,
            "claims_unverified": report.claims_unverified,
            "claims": claims_data,
        },
    )
    db.add(record)
    return record


def emit_metrics(report: FactVerificationReport) -> None:
    """Record bounded metric families for one completed report."""
    metrics.inc("fact_verification_requests_total", {"result": "completed"})
    for check in report.claims:
        metrics.inc("fact_verification_claims_total", {"verdict": check.verdict})
    metrics.inc(
        "fact_verification_results_total",
        {"status": report.overall_status},
    )


def emit_audit_event(
    event_type: str,
    *,
    outcome: str,
    user_id: Any = None,
    project_id: Any = None,
    source_id: Any = None,
    job_id: Any = None,
    output_id: Any = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Best-effort Phase 11K audit emission for fact-verification operations.

    Reuses the existing ``app.core.audit.emit_security_event`` sink only — no
    second audit system. The payload carries no claim text, evidence text,
    prompts, or source contents; only safe operational metadata (bounded
    counts/status plus the object identifiers already accepted by the
    established audit convention, e.g. ``output_id`` in Phase 11M events).

    Fail-safe by contract: if the audit sink raises, the exception is contained
    here so fact verification itself is never broken and the failure never leaks
    to the caller.
    """
    payload = dict(details or {})
    if output_id is not None:
        payload["output_id"] = str(output_id)
    try:
        audit.emit_security_event(
            event_type,
            outcome=outcome,
            user_id=str(user_id) if user_id is not None else None,
            project_id=str(project_id) if project_id is not None else None,
            source_id=str(source_id) if source_id is not None else None,
            job_id=str(job_id) if job_id is not None else None,
            reason=reason,
            details=payload,
        )
    except Exception:  # noqa: BLE001 — fail-safe: audit must never break verification
        logger.warning(
            "fact_verification_audit_emit_failed",
            event_type=event_type,
            error="audit-sink-unavailable",
        )
