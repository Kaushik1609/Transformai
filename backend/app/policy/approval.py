"""
TransformIQ / KaryaSetu AI — Human Approval / Controlled Release Layer (Phase 2F)

Pure-Python domain logic governing human approval and controlled release
of generated transformation artifacts across dissemination destinations.

Core Invariant:
    Phase 2D Dissemination Policy MUST ALWAYS take precedence over human approval.
    An approval can NEVER turn a Phase 2D BLOCK into an ALLOW.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.policy.classification import (
    InformationClassification,
    normalize_classification,
)
from app.policy.dissemination import (
    DisseminationDecision,
    DisseminationDecisionOutcome,
    DisseminationDestination,
    normalize_destination,
)


class ApprovalStatus(str, Enum):
    """Authoritative approval states for an output and dissemination destination."""

    HARD_BLOCKED = "HARD_BLOCKED"
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"

    def __str__(self) -> str:
        return self.value


class ApprovalAction(str, Enum):
    """Operator action submitted to approval engine."""

    APPROVE = "approve"
    REJECT = "reject"

    def __str__(self) -> str:
        return self.value


class InvalidApprovalTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""


class PolicyHardBlockedError(PermissionError):
    """Raised when an approval is attempted on a destination hard-blocked by Phase 2D."""


class VerificationFailedApprovalError(ValueError):
    """Raised when approval is attempted on an output whose fact verification failed."""


class StaleApprovalError(ValueError):
    """Raised when approval is invalid because source/classification/policy changed."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_initial_approval_status(
    classification: InformationClassification | str,
    destination: DisseminationDestination | str,
    dissemination_decision: DisseminationDecision,
) -> ApprovalStatus:
    """Deterministically determine the approval status for a classification and destination.

    1. Phase 2D supremacy: If dissemination is not allowed (BLOCK), status is HARD_BLOCKED.
    2. PUBLIC classification:
       - INTERNAL, REVIEW, DOWNLOAD, PRESENTATION: NOT_REQUIRED
       - PUBLIC_WEB, LINKEDIN, X: PENDING_APPROVAL (external broadcast requires sign-off)
    3. INTERNAL, CONFIDENTIAL, RESTRICTED:
       - INTERNAL, REVIEW: NOT_REQUIRED (in-app preview permitted)
       - DOWNLOAD, PRESENTATION: PENDING_APPROVAL (export/download requires sign-off)
       - All external destinations: HARD_BLOCKED (via step 1)
    """
    if not dissemination_decision.allowed or dissemination_decision.decision == DisseminationDecisionOutcome.BLOCK:
        return ApprovalStatus.HARD_BLOCKED

    norm_class = normalize_classification(classification)
    norm_dest = normalize_destination(destination)

    if norm_class == InformationClassification.PUBLIC:
        if norm_dest in (
            DisseminationDestination.INTERNAL,
            DisseminationDestination.REVIEW,
            DisseminationDestination.DOWNLOAD,
            DisseminationDestination.PRESENTATION,
        ):
            return ApprovalStatus.NOT_REQUIRED
        if norm_dest in (
            DisseminationDestination.PUBLIC_WEB,
            DisseminationDestination.LINKEDIN,
            DisseminationDestination.X,
        ):
            return ApprovalStatus.PENDING_APPROVAL

    # For INTERNAL, CONFIDENTIAL, RESTRICTED:
    if norm_dest in (
        DisseminationDestination.INTERNAL,
        DisseminationDestination.REVIEW,
    ):
        return ApprovalStatus.NOT_REQUIRED

    if norm_dest in (
        DisseminationDestination.DOWNLOAD,
        DisseminationDestination.PRESENTATION,
    ):
        return ApprovalStatus.PENDING_APPROVAL

    return ApprovalStatus.HARD_BLOCKED


def validate_approval_transition(
    current_status: ApprovalStatus | str,
    action: ApprovalAction | str,
    *,
    rejection_reason: str | None = None,
) -> ApprovalStatus:
    """Validate and compute the next approval state based on requested action.

    Fails closed:
    - HARD_BLOCKED cannot be approved or rejected.
    - REJECTED is a terminal state.
    - APPROVED cannot be approved again (double approval).
    - Action 'reject' strictly requires a non-empty rejection_reason.
    """
    curr = ApprovalStatus(str(current_status))
    act = ApprovalAction(str(action).lower())

    if curr == ApprovalStatus.HARD_BLOCKED:
        raise PolicyHardBlockedError(
            "Cannot modify approval state for a HARD_BLOCKED destination. "
            "Phase 2D dissemination policy strictly prohibits this release."
        )

    if curr == ApprovalStatus.REJECTED:
        raise InvalidApprovalTransitionError(
            "Cannot transition from REJECTED state. REJECTED is terminal for this artifact. "
            "A new transformation job must be executed."
        )

    if act == ApprovalAction.APPROVE:
        if curr == ApprovalStatus.APPROVED:
            raise InvalidApprovalTransitionError(
                "Destination is already APPROVED. Double approval is not permitted."
            )
        if curr in (ApprovalStatus.PENDING_APPROVAL, ApprovalStatus.REVOKED, ApprovalStatus.NOT_REQUIRED):
            return ApprovalStatus.APPROVED
        raise InvalidApprovalTransitionError(
            f"Cannot approve artifact in state {curr.value}."
        )

    if act == ApprovalAction.REJECT:
        if not rejection_reason or not rejection_reason.strip():
            raise ValueError("Rejection requires a non-empty rejection_reason.")
        if curr in (ApprovalStatus.PENDING_APPROVAL, ApprovalStatus.APPROVED, ApprovalStatus.REVOKED, ApprovalStatus.NOT_REQUIRED):
            return ApprovalStatus.REJECTED
        raise InvalidApprovalTransitionError(
            f"Cannot reject artifact in state {curr.value}."
        )

    raise InvalidApprovalTransitionError(f"Unsupported approval action: {action!r}.")


class DestinationApprovalRecord(BaseModel):
    """Canonical persistent metadata schema for an approval decision on a single destination."""

    destination: str
    approval_status: str
    approval_id: str | None = None
    decision: str | None = None
    approver_id: str | None = None
    approver_email: str | None = None
    approver_role: str | None = None
    approved_at: str | None = None
    rejection_reason: str | None = None
    comments: str | None = None
    self_approved: bool = False
    policy_reason: str | None = None

    # Stale-detection snapshots
    classification_snapshot: str | None = None
    verification_status_snapshot: str | None = None
    source_hash_snapshot: str | None = None
    policy_id_snapshot: str | None = None

    model_config = ConfigDict(extra="forbid")


class OutputApprovalMetadata(BaseModel):
    """Aggregate approval metadata envelope stored in Output.output_metadata['approval']."""

    destinations: dict[str, DestinationApprovalRecord] = Field(default_factory=dict)
    latest_approval_id: str | None = None

    model_config = ConfigDict(extra="forbid")


def generate_approval_id() -> str:
    """Generate a unique, stable approval reference identifier."""
    return f"appr-{uuid.uuid4()}"
