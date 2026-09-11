"""Phase 12B — Deterministic trust-status evaluation for generated outputs.

Evaluates a completed output's trustworthiness by combining signals from
existing verification, security, integrity, and fact-verification systems.
No LLM calls, no arbitrary scores — only explicit, deterministic reason codes
and a three-state status (TRUSTED / CAUTION / UNVERIFIED).

The trust-status module sits *alongside* the existing verification pipeline
and never modifies the generation or verification workflow.  It is a read-only
aggregation layer over persisted signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_TRUSTED = "TRUSTED"
STATUS_CAUTION = "CAUTION"
STATUS_UNVERIFIED = "UNVERIFIED"

# ---------------------------------------------------------------------------
# Reason codes (machine-readable, deterministic)
# ---------------------------------------------------------------------------
# Positive signals
RC_VERIFICATION_PASSED = "VERIFICATION_PASSED"
RC_GROUNDING_STRONG = "GROUNDING_STRONG"
RC_SECURITY_VALID = "SECURITY_VALID"
RC_INTEGRITY_RECORDED = "INTEGRITY_RECORDED"
RC_FACTS_ALL_SUPPORTED = "FACTS_ALL_SUPPORTED"

# Warning signals
RC_VERIFICATION_WARNING = "VERIFICATION_WARNING"
RC_GROUNDING_WEAK = "GROUNDING_WEAK"
RC_SECURITY_WARNING = "SECURITY_WARNING"
RC_INTEGRITY_UNAVAILABLE = "INTEGRITY_UNAVAILABLE"
RC_FACTS_PARTIAL_SUPPORT = "FACTS_PARTIAL_SUPPORT"
RC_FACTS_CONTRADICTED = "FACTS_CONTRADICTED"

# Failure / blocking signals
RC_VERIFICATION_FAILED = "VERIFICATION_FAILED"
RC_SECURITY_BLOCKED = "SECURITY_BLOCKED"
RC_INTEGRITY_TAMPERED = "INTEGRITY_TAMPERED"

# Missing / insufficient signals
RC_OUTPUT_INCOMPLETE = "OUTPUT_INCOMPLETE"
RC_NO_VERIFICATION_DATA = "NO_VERIFICATION_DATA"
RC_NO_GROUNDING_DATA = "NO_GROUNDING_DATA"
RC_NO_INTEGRITY_DATA = "NO_INTEGRITY_DATA"
RC_NO_FACT_VERIFICATION = "NO_FACT_VERIFICATION"

# Fact-verification generator marker (matches Phase 11N)
_FACT_CHECK_GENERATOR = "deterministic-phase11n-factcheck"

# Trusted requires ALL of these signal categories to be present and positive.
_TRUSTED_REQUIRED_SIGNALS = frozenset(
    {"grounding", "security", "integrity", "fact_verification"}
)

# A status is caution if any of these reason codes appear.
_CAUTION_REASONS = frozenset(
    {
        RC_VERIFICATION_WARNING,
        RC_GROUNDING_WEAK,
        RC_SECURITY_WARNING,
        RC_INTEGRITY_UNAVAILABLE,
        RC_FACTS_PARTIAL_SUPPORT,
    }
)

# A status is unverified if any of these reason codes appear.
_UNVERIFIED_REASONS = frozenset(
    {
        RC_OUTPUT_INCOMPLETE,
        RC_NO_VERIFICATION_DATA,
        RC_NO_GROUNDING_DATA,
        RC_NO_INTEGRITY_DATA,
        RC_NO_FACT_VERIFICATION,
    }
)


@dataclass(frozen=True)
class SignalResult:
    """A single signal category's deterministic assessment."""

    category: str
    present: bool
    status: str  # "positive" | "warning" | "failure" | "missing"
    reason_code: str
    detail: str


@dataclass(frozen=True)
class TrustStatus:
    """The assembled trust-status result for one output."""

    status: str
    reason_codes: list[str]
    signals: list[SignalResult]
    output_id: str
    output_type: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API response."""
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "signals": [
                {
                    "category": s.category,
                    "present": s.present,
                    "status": s.status,
                    "reason_code": s.reason_code,
                    "detail": s.detail,
                }
                for s in self.signals
            ],
            "output_id": self.output_id,
            "output_type": self.output_type,
        }


# ---------------------------------------------------------------------------
# Individual signal evaluators
# ---------------------------------------------------------------------------

def _evaluate_grounding(
    verification_results: list[dict[str, Any]],
) -> SignalResult:
    """Evaluate grounding signals from VerificationResult records."""
    if not verification_results:
        return SignalResult(
            category="grounding",
            present=False,
            status="missing",
            reason_code=RC_NO_GROUNDING_DATA,
            detail="No verification results available for this output.",
        )

    vr = verification_results[0]
    overall = vr.get("overall_status", "")
    grounding_score = vr.get("grounding_score")

    if overall == "passed" and grounding_score is not None and grounding_score >= 0.5:
        return SignalResult(
            category="grounding",
            present=True,
            status="positive",
            reason_code=RC_GROUNDING_STRONG,
            detail=f"Grounding score {grounding_score:.2f} with passed verification.",
        )
    if overall == "passed":
        return SignalResult(
            category="grounding",
            present=True,
            status="positive",
            reason_code=RC_VERIFICATION_PASSED,
            detail="Verification passed.",
        )
    if overall == "warning":
        return SignalResult(
            category="grounding",
            present=True,
            status="warning",
            reason_code=RC_VERIFICATION_WARNING,
            detail="Verification produced warnings.",
        )
    if overall == "failed":
        return SignalResult(
            category="grounding",
            present=True,
            status="failure",
            reason_code=RC_VERIFICATION_FAILED,
            detail="Verification failed.",
        )

    return SignalResult(
        category="grounding",
        present=False,
        status="missing",
        reason_code=RC_NO_GROUNDING_DATA,
        detail="Verification result present but status is unrecognized.",
    )


def _evaluate_security(
    output_metadata: dict[str, Any] | None,
) -> SignalResult:
    """Evaluate L5 output security status from output_metadata."""
    meta = (output_metadata or {}).get("security")
    if not isinstance(meta, dict) or not meta:
        return SignalResult(
            category="security",
            present=False,
            status="missing",
            reason_code=RC_NO_VERIFICATION_DATA,
            detail="No security validation record available.",
        )

    status = meta.get("status", "")
    if status == "valid":
        return SignalResult(
            category="security",
            present=True,
            status="positive",
            reason_code=RC_SECURITY_VALID,
            detail="Output passed L5 security validation.",
        )
    if status == "warning":
        return SignalResult(
            category="security",
            present=True,
            status="warning",
            reason_code=RC_SECURITY_WARNING,
            detail="Output security validation produced warnings.",
        )
    if status == "blocked":
        return SignalResult(
            category="security",
            present=True,
            status="failure",
            reason_code=RC_SECURITY_BLOCKED,
            detail="Output was blocked by L5 security validation.",
        )

    return SignalResult(
        category="security",
        present=False,
        status="missing",
        reason_code=RC_NO_VERIFICATION_DATA,
        detail="Security status unrecognized.",
    )


def _evaluate_integrity(
    output_metadata: dict[str, Any] | None,
) -> SignalResult:
    """Evaluate artifact integrity status from output_metadata."""
    meta = (output_metadata or {}).get("integrity")
    if not isinstance(meta, dict) or not meta:
        return SignalResult(
            category="integrity",
            present=False,
            status="missing",
            reason_code=RC_NO_INTEGRITY_DATA,
            detail="No integrity record available.",
        )

    status = meta.get("status", "")
    if status == "recorded":
        return SignalResult(
            category="integrity",
            present=True,
            status="positive",
            reason_code=RC_INTEGRITY_RECORDED,
            detail="Artifact integrity was recorded on the ledger.",
        )
    if status == "unavailable":
        return SignalResult(
            category="integrity",
            present=True,
            status="warning",
            reason_code=RC_INTEGRITY_UNAVAILABLE,
            detail="Integrity ledger was unavailable during recording.",
        )
    if status == "tampered":
        return SignalResult(
            category="integrity",
            present=True,
            status="failure",
            reason_code=RC_INTEGRITY_TAMPERED,
            detail="Artifact does not match its recorded digest.",
        )

    return SignalResult(
        category="integrity",
        present=True,
        status="warning",
        reason_code=RC_INTEGRITY_UNAVAILABLE,
        detail=f"Integrity status is {status!r} (not recorded).",
    )


def _evaluate_fact_verification(
    verification_results: list[dict[str, Any]],
) -> SignalResult:
    """Evaluate fact-verification signals from Phase 11N VerificationResult records."""
    fact_check_results = [
        vr
        for vr in verification_results
        if isinstance(vr.get("details"), dict)
        and vr["details"].get("generator") == _FACT_CHECK_GENERATOR
    ]

    if not fact_check_results:
        return SignalResult(
            category="fact_verification",
            present=False,
            status="missing",
            reason_code=RC_NO_FACT_VERIFICATION,
            detail="No fact-verification report available.",
        )

    vr = fact_check_results[0]
    details = vr.get("details", {})
    contradicted = details.get("claims_contradicted", 0)
    unverified = details.get("claims_unverified", 0)
    checked = details.get("claims_checked", 0)

    if contradicted > 0:
        return SignalResult(
            category="fact_verification",
            present=True,
            status="failure",
            reason_code=RC_FACTS_CONTRADICTED,
            detail=f"{contradicted} claim(s) contradicted by source evidence.",
        )

    if unverified > 0 and checked > 0:
        return SignalResult(
            category="fact_verification",
            present=True,
            status="warning",
            reason_code=RC_FACTS_PARTIAL_SUPPORT,
            detail=(
                f"{checked - unverified} of {checked} claim(s) supported; "
                f"{unverified} unverified."
            ),
        )

    if checked > 0:
        return SignalResult(
            category="fact_verification",
            present=True,
            status="positive",
            reason_code=RC_FACTS_ALL_SUPPORTED,
            detail=f"All {checked} claim(s) supported by source evidence.",
        )

    return SignalResult(
        category="fact_verification",
        present=True,
        status="positive",
        reason_code=RC_FACTS_ALL_SUPPORTED,
        detail="No checkable claims found; no contradictions detected.",
    )


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_trust_status(
    *,
    output_id: str,
    output_type: str,
    output_status: str,
    output_metadata: dict[str, Any] | None = None,
    verification_results: list[dict[str, Any]] | None = None,
) -> TrustStatus:
    """Deterministically compute trust status for a single output.

    Parameters
    ----------
    output_id : str
        The output's UUID string.
    output_type : str
        The output type (summary, linkedin, x, etc.).
    output_status : str
        The output's lifecycle status (generating, completed, failed).
    output_metadata : dict or None
        The output's ``output_metadata`` JSON blob.
    verification_results : list of dict or None
        Serialized ``VerificationResult`` records for this output.

    Returns
    -------
    TrustStatus
        Frozen dataclass with status, reason codes, and signals.
    """
    vr_list = verification_results or []

    # --- Fast path: incomplete output ---
    if output_status != "completed":
        return TrustStatus(
            status=STATUS_UNVERIFIED,
            reason_codes=[RC_OUTPUT_INCOMPLETE],
            signals=[
                SignalResult(
                    category="output",
                    present=False,
                    status="missing",
                    reason_code=RC_OUTPUT_INCOMPLETE,
                    detail=f"Output status is {output_status!r} (not completed).",
                )
            ],
            output_id=output_id,
            output_type=output_type,
        )

    # --- Evaluate each signal category ---
    signals = [
        _evaluate_grounding(vr_list),
        _evaluate_security(output_metadata),
        _evaluate_integrity(output_metadata),
        _evaluate_fact_verification(vr_list),
    ]

    reason_codes = [s.reason_code for s in signals]

    # --- Determine overall status ---
    has_failure = any(s.status == "failure" for s in signals)
    has_warning = any(s.status == "warning" for s in signals)
    has_missing = any(s.status == "missing" for s in signals)
    has_positive = any(s.status == "positive" for s in signals)

    if has_failure:
        # Any blocking signal → CAUTION (never TRUSTED when there's a failure)
        return TrustStatus(
            status=STATUS_CAUTION,
            reason_codes=reason_codes,
            signals=signals,
            output_id=output_id,
            output_type=output_type,
        )

    # Insufficient information to make a trustworthy determination →
    # UNVERIFIED.  This happens when no positive signal exists (e.g. all
    # signals are missing, or there is only a reference-less warning).
    if not has_positive:
        return TrustStatus(
            status=STATUS_UNVERIFIED,
            reason_codes=reason_codes,
            signals=signals,
            output_id=output_id,
            output_type=output_type,
        )

    if has_warning or has_missing:
        return TrustStatus(
            status=STATUS_CAUTION,
            reason_codes=reason_codes,
            signals=signals,
            output_id=output_id,
            output_type=output_type,
        )

    # All signals present and positive → TRUSTED
    return TrustStatus(
        status=STATUS_TRUSTED,
        reason_codes=reason_codes,
        signals=signals,
        output_id=output_id,
        output_type=output_type,
    )
