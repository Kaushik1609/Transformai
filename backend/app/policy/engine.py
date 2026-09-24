"""
TransformIQ / KaryaSetu AI — Deterministic Policy Engine (Phase 2B)

A pure-Python, zero-LLM policy engine responsible for policy decisions.

Core Principle:
    LLM MAY RECOMMEND.
    POLICY ENGINE MUST DECIDE.

The engine is deterministic, offline, and fails closed for invalid or
disallowed combinations. Given the same inputs, it always yields the exact
same PolicyDecision.
"""
from __future__ import annotations

from typing import Any

from app.policy.classification import (
    InformationClassification,
    InvalidClassificationError,
    normalize_classification,
)
from app.policy.schemas import (
    PolicyDecision,
    PolicyEvaluationContext,
    ProcessingRoute,
    ProviderCategory,
)

# Providers categorized as external cloud services
_EXTERNAL_CLOUD_PROVIDERS = frozenset(
    {
        "openai",
        "gemini",
        "anthropic",
        "azure",
        "azure_openai",
        "aws_bedrock",
        "gcp_vertex",
        "cloud",
        "external_cloud",
        "external",
    }
)

# Providers categorized as private or on-premises / local services
_PRIVATE_LOCAL_PROVIDERS = frozenset(
    {
        "local",
        "private",
        "ollama",
        "vllm",
        "on_prem",
        "on_premises",
        "self_hosted",
        "in_house",
        "private_local",
    }
)

# Providers categorized as test or offline development mocks
_TEST_DEV_PROVIDERS = frozenset(
    {
        "fake",
        "mock",
        "test",
        "dev",
        "development",
        "development (fake - testing purpose)",
    }
)

# Output types considered public social dissemination
_PUBLIC_SOCIAL_OUTPUTS = frozenset(
    {
        "linkedin",
        "x",
        "twitter",
        "social",
        "public_post",
    }
)

# Environments recognized as production
_PRODUCTION_ENVIRONMENTS = frozenset(
    {
        "production",
        "prod",
        "live",
    }
)

# Valid environments recognized by the system
_VALID_ENVIRONMENTS = frozenset(
    {
        "cloud",
        "local",
        "private",
        "hybrid",
        "development",
        "dev",
        "test",
        "testing",
        "staging",
        "production",
        "prod",
        "live",
        "offline",
        "auto",
    }
)


def categorize_provider(provider_name: str | None) -> ProviderCategory | None:
    """Resolve a provider identifier to its conceptual category.

    Reasons about provider category rather than hardcoding vendor lock-in.
    Returns None if the provider cannot be safely categorized (fail closed).
    """
    if not provider_name:
        return None

    clean = str(provider_name).strip().lower()

    if clean in _EXTERNAL_CLOUD_PROVIDERS:
        return ProviderCategory.EXTERNAL_CLOUD

    if clean in _PRIVATE_LOCAL_PROVIDERS:
        return ProviderCategory.PRIVATE_LOCAL

    if clean in _TEST_DEV_PROVIDERS:
        return ProviderCategory.TEST_DEVELOPMENT

    # Prefix-based heuristics for extensible naming (e.g. "openai/gpt-4o", "local:llama-3")
    if clean.startswith(("openai", "gemini", "anthropic", "azure", "cloud")):
        return ProviderCategory.EXTERNAL_CLOUD
    if clean.startswith(("local", "private", "ollama", "vllm")):
        return ProviderCategory.PRIVATE_LOCAL
    if clean.startswith(("fake", "mock", "test")):
        return ProviderCategory.TEST_DEVELOPMENT

    return None


class PolicyEngine:
    """Deterministic policy engine for KaryaSetu AI.

    Evaluates information classification, requested outputs, model provider,
    and processing environment to determine whether a transformation is permitted.
    """

    def evaluate(self, context: PolicyEvaluationContext) -> PolicyDecision:
        """Evaluate the policy context and return an authoritative PolicyDecision.

        Deterministic: no randomness, no clock dependency, zero LLM calls.
        Fails closed on any unexpected or invalid input.
        """
        # 1. Validate classification
        try:
            classification = normalize_classification(context.classification)
        except InvalidClassificationError as exc:
            return PolicyDecision(
                allowed=False,
                reason=f"Policy rejection: {str(exc)}",
                classification=InformationClassification.RESTRICTED,
                processing_route=ProcessingRoute.BLOCKED.value,
                requires_review=False,
                details={"error": "invalid_classification", "raw_input": str(context.classification)},
            )

        # 2. Validate environment
        env = str(context.environment).strip().lower() if context.environment else "cloud"
        if env not in _VALID_ENVIRONMENTS:
            return PolicyDecision(
                allowed=False,
                reason=f"Policy rejection: Unsupported processing environment {context.environment!r}.",
                classification=classification,
                processing_route=ProcessingRoute.BLOCKED.value,
                requires_review=False,
                details={"error": "unsupported_environment", "environment": context.environment},
            )

        is_production = env in _PRODUCTION_ENVIRONMENTS

        # 3. Categorize model provider
        category = categorize_provider(context.requested_provider)
        if category is None:
            return PolicyDecision(
                allowed=False,
                reason=f"Policy rejection: Unknown or unsupported model provider {context.requested_provider!r}.",
                classification=classification,
                processing_route=ProcessingRoute.BLOCKED.value,
                requires_review=False,
                details={"error": "unsupported_provider", "provider": context.requested_provider},
            )

        # 4. Enforce Fake Provider Safety: In production, fake provider is disallowed
        if category == ProviderCategory.TEST_DEVELOPMENT and is_production:
            return PolicyDecision(
                allowed=False,
                reason="Policy rejection: Test/mock provider 'fake' is not permitted in production environment.",
                classification=classification,
                processing_route=ProcessingRoute.BLOCKED.value,
                requires_review=False,
                details={"error": "fake_provider_in_production", "environment": env},
            )

        # 5. Output Dissemination Policy Check
        # Check if requested outputs contain public social dissemination channels
        requested_outputs_norm = [str(o).strip().lower() for o in context.requested_outputs]
        has_public_social = any(o in _PUBLIC_SOCIAL_OUTPUTS for o in requested_outputs_norm)

        if has_public_social:
            if classification == InformationClassification.RESTRICTED:
                return PolicyDecision(
                    allowed=False,
                    reason="Policy rejection: Restricted information is strictly prohibited from public dissemination (LinkedIn/X).",
                    classification=classification,
                    processing_route=ProcessingRoute.BLOCKED.value,
                    requires_review=False,
                    details={
                        "violation": "restricted_public_dissemination",
                        "outputs": context.requested_outputs,
                    },
                )
            if classification == InformationClassification.CONFIDENTIAL:
                return PolicyDecision(
                    allowed=False,
                    reason="Policy restriction: Confidential information cannot be disseminated to public channels (LinkedIn/X) without prior review.",
                    classification=classification,
                    processing_route=ProcessingRoute.BLOCKED.value,
                    requires_review=True,
                    details={
                        "violation": "confidential_public_dissemination",
                        "outputs": context.requested_outputs,
                    },
                )

        # 6. Model Provider Processing Route Policy Check
        # RESTRICTED: External cloud processing denied; private/local processing required.
        if classification == InformationClassification.RESTRICTED:
            if category == ProviderCategory.EXTERNAL_CLOUD:
                return PolicyDecision(
                    allowed=False,
                    reason="Policy rejection: Restricted information cannot be processed by external cloud providers under KaryaSetu policy.",
                    classification=classification,
                    processing_route=ProcessingRoute.BLOCKED.value,
                    requires_review=False,
                    details={
                        "violation": "restricted_cloud_processing",
                        "provider_category": category.value,
                    },
                )
            # Private/local or test/development (in dev/test) is allowed
            return PolicyDecision(
                allowed=True,
                reason="Permitted: Restricted information routed to private/local processing under policy.",
                classification=classification,
                processing_route=ProcessingRoute.PRIVATE_LOCAL.value,
                requires_review=False,
                details={"provider_category": category.value},
            )

        # CONFIDENTIAL: Private/local processing required; external cloud processing denied.
        if classification == InformationClassification.CONFIDENTIAL:
            if category == ProviderCategory.EXTERNAL_CLOUD:
                return PolicyDecision(
                    allowed=False,
                    reason="Policy rejection: Confidential information requires private or local model processing under KaryaSetu policy. External cloud processing is denied.",
                    classification=classification,
                    processing_route=ProcessingRoute.BLOCKED.value,
                    requires_review=False,
                    details={
                        "violation": "confidential_cloud_processing",
                        "provider_category": category.value,
                    },
                )
            return PolicyDecision(
                allowed=True,
                reason="Permitted: Confidential information routed to private/local processing under policy.",
                classification=classification,
                processing_route=ProcessingRoute.PRIVATE_LOCAL.value,
                requires_review=False,
                details={"provider_category": category.value},
            )

        # INTERNAL: Controlled internal processing allowed
        if classification == InformationClassification.INTERNAL:
            # Both cloud and private/local allowed under enterprise internal controls
            route = (
                ProcessingRoute.PRIVATE_LOCAL.value
                if category == ProviderCategory.PRIVATE_LOCAL
                else ProcessingRoute.CONTROLLED_INTERNAL.value
            )
            return PolicyDecision(
                allowed=True,
                reason="Permitted: Internal information permitted for controlled processing.",
                classification=classification,
                processing_route=route,
                requires_review=False,
                details={"provider_category": category.value},
            )

        # PUBLIC: Cloud processing allowed according to configured policy
        if classification == InformationClassification.PUBLIC:
            route = (
                ProcessingRoute.PRIVATE_LOCAL.value
                if category == ProviderCategory.PRIVATE_LOCAL
                else ProcessingRoute.CLOUD.value
            )
            return PolicyDecision(
                allowed=True,
                reason="Permitted: Public information permitted for cloud processing.",
                classification=classification,
                processing_route=route,
                requires_review=False,
                details={"provider_category": category.value},
            )

        # Defensive fallback: fail closed
        return PolicyDecision(
            allowed=False,
            reason="Policy rejection: Unhandled policy state (failing closed).",
            classification=classification,
            processing_route=ProcessingRoute.BLOCKED.value,
            requires_review=False,
            details={"fallback": True},
        )


_DEFAULT_ENGINE = PolicyEngine()


def get_policy_engine() -> PolicyEngine:
    """Return the singleton PolicyEngine instance."""
    return _DEFAULT_ENGINE
