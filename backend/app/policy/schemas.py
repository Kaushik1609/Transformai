"""
TransformIQ / KaryaSetu AI — Policy Schemas (Phase 2B)

Pydantic schemas and enums for deterministic policy evaluation.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.policy.classification import InformationClassification


class ProviderCategory(str, Enum):
    """Categorisation of execution and model providers."""

    EXTERNAL_CLOUD = "EXTERNAL_CLOUD"
    PRIVATE_LOCAL = "PRIVATE_LOCAL"
    TEST_DEVELOPMENT = "TEST_DEVELOPMENT"
    UNKNOWN = "UNKNOWN"


class ProcessingRoute(str, Enum):
    """Permitted or blocked processing routes."""

    CLOUD = "cloud"
    CONTROLLED_INTERNAL = "controlled_internal"
    PRIVATE_LOCAL = "private_local"
    BLOCKED = "blocked"


class PolicyEvaluationContext(BaseModel):
    """Inputs required for a deterministic policy decision."""

    classification: InformationClassification = Field(
        ...,
        description="Source or request information classification label.",
    )
    requested_outputs: list[str] = Field(
        default_factory=list,
        description="Target output types requested (e.g. ['summary', 'linkedin']).",
    )
    requested_provider: str = Field(
        default="openai",
        description="Name or identifier of the requested model provider.",
    )
    environment: str = Field(
        default="cloud",
        description="Target processing environment (e.g. 'cloud', 'local', 'development', 'production').",
    )
    organization_policy: dict[str, Any] | None = Field(
        default=None,
        description="Optional organization-level policy configuration or constraints.",
    )

    model_config = ConfigDict(extra="forbid")


class PolicyDecision(BaseModel):
    """Deterministic policy decision outcome produced by the PolicyEngine.

    The LLM may recommend; the Policy Engine must decide.
    """

    allowed: bool = Field(
        ...,
        description="Whether the requested transformation is permitted under policy.",
    )
    reason: str = Field(
        ...,
        description="Clear human-readable justification for the decision.",
    )
    classification: InformationClassification = Field(
        ...,
        description="The evaluated information classification.",
    )
    processing_route: str = Field(
        ...,
        description="Authoritative processing route: 'cloud', 'controlled_internal', 'private_local', or 'blocked'.",
    )
    requires_review: bool = Field(
        default=False,
        description="True if human or supervisor review is required before dissemination/execution.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured non-sensitive operational details of the evaluation.",
    )

    model_config = ConfigDict(extra="forbid")


class RouteDecision(BaseModel):
    """Immutable outcome produced by the PolicyRouter.

    Captures the resolved compliant provider, model, route, and failure codes (if any).
    Never contains secret keys, credentials, prompts, or source text.
    """

    allowed: bool = Field(
        ...,
        description="Whether a compliant route and provider could be resolved.",
    )
    provider_id: str = Field(
        ...,
        description="Canonical identifier of the resolved provider (e.g. 'openai', 'local', 'fake').",
    )
    model_id: str = Field(
        ...,
        description="Target model identifier.",
    )
    provider_category: ProviderCategory = Field(
        ...,
        description="Conceptual category of the resolved provider.",
    )
    processing_route: ProcessingRoute = Field(
        ...,
        description="Target processing route.",
    )
    classification: InformationClassification = Field(
        ...,
        description="The evaluated information classification.",
    )
    reason: str = Field(
        ...,
        description="Human-readable justification for the routing outcome.",
    )
    error_code: str | None = Field(
        default=None,
        description="Standardized error code if routing failed (e.g. COMPLIANT_PROVIDER_UNAVAILABLE).",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe operational metadata for audit and observability.",
    )

    model_config = ConfigDict(extra="forbid")
