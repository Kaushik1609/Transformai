"""
TransformIQ / KaryaSetu AI — Dissemination Control Layer (Phase 2D)

A pure-Python, zero-LLM deterministic policy engine controlling dissemination
of generated transformation outputs to external and internal destinations.

Core Principle:
    CLASSIFICATION -> POLICY -> AI ROUTE -> TRANSFORMATION -> OUTPUT ->
    DISSEMINATION DECISION -> ALLOW / BLOCK / REVIEW -> AUDIT

The dissemination layer is strictly separated from AI generation.
The LLM must NEVER decide whether an artifact may be disseminated or shared.
The deterministic policy layer authoritatively enforces the decision.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.policy.classification import (
    InformationClassification,
    InvalidClassificationError,
    normalize_classification,
)


class DisseminationDestination(str, Enum):
    """Supported dissemination destinations for generated artifacts."""

    INTERNAL = "INTERNAL"
    REVIEW = "REVIEW"
    DOWNLOAD = "DOWNLOAD"
    PRESENTATION = "PRESENTATION"
    PUBLIC_WEB = "PUBLIC_WEB"
    LINKEDIN = "LINKEDIN"
    X = "X"

    def __str__(self) -> str:
        return self.value


class DisseminationDecisionOutcome(str, Enum):
    """Deterministic dissemination decision outcomes."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"

    def __str__(self) -> str:
        return self.value


class InvalidDestinationError(ValueError):
    """Raised when an unrecognized, malformed, or unsupported destination is provided."""


# Canonical set of valid uppercase string representations.
VALID_DESTINATIONS = frozenset(d.value for d in DisseminationDestination)

# Standard policy version identifier.
DISSEMINATION_POLICY_ID = "karyasetu-dissemination-v1"


def normalize_destination(
    value: str | DisseminationDestination | None,
) -> DisseminationDestination:
    """Validate and normalize a dissemination destination string.

    Fails closed:
    - None or empty string raises InvalidDestinationError (never silently allowed).
    - Valid destinations are accepted case-insensitively with leading/trailing whitespace stripped.
    - Any unknown or unsupported string raises InvalidDestinationError (fail-closed).
    """
    if value is None:
        raise InvalidDestinationError("Dissemination destination cannot be None or missing.")

    if isinstance(value, DisseminationDestination):
        return value

    if isinstance(value, Enum):
        raw = str(value.value).strip().upper()
    else:
        raw = str(value).strip().upper()

    if not raw:
        raise InvalidDestinationError("Dissemination destination cannot be empty.")

    # Handle common alias variations cleanly
    if raw in ("TWITTER", "POST_X"):
        raw = "X"
    elif raw in ("WEB", "PUBLIC", "PUBLICWEB"):
        raw = "PUBLIC_WEB"

    if raw in VALID_DESTINATIONS:
        return DisseminationDestination(raw)

    raise InvalidDestinationError(
        f"Invalid or unsupported dissemination destination: {value!r}. "
        f"Allowed destinations are: {', '.join(sorted(VALID_DESTINATIONS))}."
    )


class DisseminationDecision(BaseModel):
    """Deterministic dissemination decision outcome produced by DisseminationEngine.

    Contains all decision context and extension points for future phases:
    artifact hash (2G), signature (2H), approval (2F), provenance (2E), and audit.
    Never exposes secrets, tokens, or raw source text.
    """

    allowed: bool = Field(
        ...,
        description="True if the dissemination decision is ALLOW, False if BLOCK or REVIEW.",
    )
    decision: DisseminationDecisionOutcome = Field(
        ...,
        description="The authoritative policy decision outcome: ALLOW, BLOCK, or REVIEW.",
    )
    classification: InformationClassification = Field(
        ...,
        description="The evaluated information classification.",
    )
    destination: str = Field(
        ...,
        description="The target dissemination destination evaluated.",
    )
    reason: str = Field(
        ...,
        description="Human-readable justification for the dissemination policy decision.",
    )
    policy_id: str = Field(
        default=DISSEMINATION_POLICY_ID,
        description="Identifier/version of the evaluated dissemination policy.",
    )

    # Future-proofing extension points for Phases 2E-2H (purely structural, no logic yet)
    artifact_hash: str | None = Field(
        default=None,
        description="Cryptographic content digest of the evaluated artifact (Phase 2G extension point).",
    )
    signature: str | None = Field(
        default=None,
        description="Digital signature envelope for approved dissemination (Phase 2H extension point).",
    )
    provenance_id: str | None = Field(
        default=None,
        description="Cryptographic provenance record identifier (Phase 2E extension point).",
    )
    approval_id: str | None = Field(
        default=None,
        description="Human governance or supervisor approval reference (Phase 2F extension point).",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive operational and audit metadata.",
    )

    model_config = ConfigDict(extra="forbid")


# Output types to primary destination mapping heuristics (OUTPUT TYPE != DESTINATION)
_OUTPUT_TYPE_PRIMARY_DESTINATION: dict[str, DisseminationDestination] = {
    "linkedin": DisseminationDestination.LINKEDIN,
    "x": DisseminationDestination.X,
    "presentation": DisseminationDestination.PRESENTATION,
    "summary": DisseminationDestination.DOWNLOAD,
    "advisory": DisseminationDestination.DOWNLOAD,
    "infographic": DisseminationDestination.DOWNLOAD,
    "video": DisseminationDestination.DOWNLOAD,
}


class DisseminationEngine:
    """Deterministic policy engine for output dissemination control.

    Evaluates source classification and target dissemination destination.
    Zero LLM calls, deterministic, offline, and fails closed on invalid inputs.

    Product policy defaults (not legal/regulatory requirements):
    - PUBLIC:
        INTERNAL allowed, REVIEW allowed, DOWNLOAD allowed, PRESENTATION allowed,
        PUBLIC_WEB allowed, LINKEDIN allowed, X allowed.
    - INTERNAL:
        INTERNAL allowed, REVIEW allowed, DOWNLOAD allowed, PRESENTATION allowed,
        PUBLIC_WEB blocked, LINKEDIN blocked, X blocked.
    - CONFIDENTIAL:
        INTERNAL allowed, REVIEW allowed, DOWNLOAD allowed, PRESENTATION allowed,
        PUBLIC_WEB blocked, LINKEDIN blocked, X blocked.
    - RESTRICTED:
        INTERNAL allowed, REVIEW allowed, DOWNLOAD allowed, PRESENTATION allowed,
        PUBLIC_WEB blocked, LINKEDIN blocked, X blocked.
    """

    POLICY_ID = DISSEMINATION_POLICY_ID

    def evaluate(
        self,
        classification: InformationClassification | str | None,
        destination: DisseminationDestination | str | None,
        *,
        output_type: str | None = None,
        artifact_hash: str | None = None,
    ) -> DisseminationDecision:
        """Evaluate dissemination policy for a classification and destination.

        Deterministic, pure-function behavior. Fails closed on any invalid
        or unknown classification or destination.
        """
        # 1. Normalize classification (fails closed on invalid label)
        try:
            norm_class = normalize_classification(classification)
        except InvalidClassificationError as exc:
            return DisseminationDecision(
                allowed=False,
                decision=DisseminationDecisionOutcome.BLOCK,
                classification=InformationClassification.RESTRICTED,
                destination=str(destination) if destination is not None else "UNKNOWN",
                reason=f"Dissemination blocked: {str(exc)}",
                policy_id=self.POLICY_ID,
                artifact_hash=artifact_hash,
                details={"error": "invalid_classification", "raw_classification": str(classification)},
            )

        # 2. Normalize destination (fails closed on missing, unknown, or malformed destination)
        try:
            norm_dest = normalize_destination(destination)
        except InvalidDestinationError as exc:
            return DisseminationDecision(
                allowed=False,
                decision=DisseminationDecisionOutcome.BLOCK,
                classification=norm_class,
                destination=str(destination) if destination is not None else "UNKNOWN",
                reason=f"Dissemination blocked: {str(exc)}",
                policy_id=self.POLICY_ID,
                artifact_hash=artifact_hash,
                details={"error": "invalid_destination", "raw_destination": str(destination)},
            )

        details: dict[str, Any] = {
            "classification": norm_class.value,
            "destination": norm_dest.value,
        }
        if output_type:
            details["output_type"] = output_type

        # 3. Deterministic policy evaluation matrix
        # PUBLIC classification allows all standard destinations
        if norm_class == InformationClassification.PUBLIC:
            return DisseminationDecision(
                allowed=True,
                decision=DisseminationDecisionOutcome.ALLOW,
                classification=norm_class,
                destination=norm_dest.value,
                reason=f"Dissemination allowed: Public information is permitted for destination '{norm_dest.value}'.",
                policy_id=self.POLICY_ID,
                artifact_hash=artifact_hash,
                details=details,
            )

        # INTERNAL, CONFIDENTIAL, RESTRICTED:
        # INTERNAL, REVIEW, DOWNLOAD, PRESENTATION are permitted
        if norm_dest in (
            DisseminationDestination.INTERNAL,
            DisseminationDestination.REVIEW,
            DisseminationDestination.DOWNLOAD,
            DisseminationDestination.PRESENTATION,
        ):
            return DisseminationDecision(
                allowed=True,
                decision=DisseminationDecisionOutcome.ALLOW,
                classification=norm_class,
                destination=norm_dest.value,
                reason=(
                    f"Dissemination allowed: {norm_class.value.capitalize()} information "
                    f"is permitted for internal destination '{norm_dest.value}'."
                ),
                policy_id=self.POLICY_ID,
                artifact_hash=artifact_hash,
                details=details,
            )

        # PUBLIC_WEB, LINKEDIN, X are blocked for non-PUBLIC classifications
        if norm_dest in (
            DisseminationDestination.PUBLIC_WEB,
            DisseminationDestination.LINKEDIN,
            DisseminationDestination.X,
        ):
            return DisseminationDecision(
                allowed=False,
                decision=DisseminationDecisionOutcome.BLOCK,
                classification=norm_class,
                destination=norm_dest.value,
                reason=(
                    f"Dissemination blocked: {norm_class.value} information "
                    f"is prohibited from external/public destination '{norm_dest.value}' under policy."
                ),
                policy_id=self.POLICY_ID,
                artifact_hash=artifact_hash,
                details=details,
            )

        # Defensive fail-closed fallback
        return DisseminationDecision(
            allowed=False,
            decision=DisseminationDecisionOutcome.BLOCK,
            classification=norm_class,
            destination=norm_dest.value,
            reason="Dissemination blocked: Unhandled destination state (failing closed).",
            policy_id=self.POLICY_ID,
            artifact_hash=artifact_hash,
            details=details,
        )

    def evaluate_all(
        self,
        classification: InformationClassification | str | None,
        *,
        output_type: str | None = None,
        artifact_hash: str | None = None,
    ) -> dict[str, DisseminationDecision]:
        """Evaluate dissemination policy for all known destinations."""
        results: dict[str, DisseminationDecision] = {}
        for dest in DisseminationDestination:
            results[dest.value] = self.evaluate(
                classification,
                dest,
                output_type=output_type,
                artifact_hash=artifact_hash,
            )
        return results

    def evaluate_output(
        self,
        classification: InformationClassification | str | None,
        output_type: str,
        destination: DisseminationDestination | str | None = None,
        *,
        artifact_hash: str | None = None,
    ) -> DisseminationDecision:
        """Evaluate dissemination for a specific output type.

        If destination is omitted, uses the primary dissemination destination
        associated with the output type (e.g. LINKEDIN for 'linkedin', X for 'x',
        DOWNLOAD for 'summary').
        """
        target_dest = destination
        if target_dest is None:
            clean_type = str(output_type).strip().lower()
            target_dest = _OUTPUT_TYPE_PRIMARY_DESTINATION.get(
                clean_type, DisseminationDestination.DOWNLOAD
            )
        return self.evaluate(
            classification,
            target_dest,
            output_type=output_type,
            artifact_hash=artifact_hash,
        )


_DEFAULT_DISSEMINATION_ENGINE = DisseminationEngine()


def get_dissemination_engine() -> DisseminationEngine:
    """Return the singleton DisseminationEngine instance."""
    return _DEFAULT_DISSEMINATION_ENGINE
