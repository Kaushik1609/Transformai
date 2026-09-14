"""
TransformIQ / KaryaSetu AI — Deterministic Policy Router (Phase 2C)

Responsible for mapping a PolicyDecision to an approved, compliant provider and
model configuration.

Core Guarantees:
- Consumes authoritative PolicyEngine decisions; does not duplicate or bypass rules.
- CONFIDENTIAL & RESTRICTED require PRIVATE_LOCAL routes; external cloud is denied.
- Zero silent fallback from sensitive private/local routes to external cloud.
- Fails closed when compliant providers are unavailable or credentials are missing.
- Safe for offline / test environments using deterministic test/mock providers.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.policy.classification import InformationClassification
from app.policy.registry import (
    ProviderDescriptor,
    ProviderRegistry,
    get_provider_registry,
)
from app.policy.schemas import (
    PolicyDecision,
    ProcessingRoute,
    ProviderCategory,
    RouteDecision,
)

# Standardized error codes for deterministic routing failures
ERROR_UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"
ERROR_COMPLIANT_PROVIDER_UNAVAILABLE = "COMPLIANT_PROVIDER_UNAVAILABLE"
ERROR_POLICY_DENIED = "POLICY_DENIED"
ERROR_PRODUCTION_TEST_PROVIDER = "PRODUCTION_TEST_PROVIDER"
ERROR_UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"

# Production environment markers
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "live"})


def _is_provider_configured(descriptor: ProviderDescriptor) -> bool:
    """Check if the necessary environment variables are set for this provider without exposing values."""
    if descriptor.requires_credentials:
        if descriptor.env_key_variable:
            val = getattr(settings, descriptor.env_key_variable, None)
            if not val or not str(val).strip():
                return False

    # For local/private providers, if a specific base URL is required/configured
    if descriptor.provider_category == ProviderCategory.PRIVATE_LOCAL:
        # local providers are considered configured if LLM_BASE_URL is set or if provider is 'local'
        # In local execution, local provider is available
        return True

    return True


class PolicyRouter:
    """Deterministic routing engine that selects compliant AI providers and models."""

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self._registry = registry or get_provider_registry()

    def resolve_route(
        self,
        classification: InformationClassification | str,
        *,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        environment: str | None = None,
        decision: PolicyDecision | None = None,
    ) -> RouteDecision:
        """Resolve a RouteDecision, evaluating PolicyEngine if decision not provided."""
        from app.policy.classification import normalize_classification
        from app.policy.engine import get_policy_engine

        norm_class = normalize_classification(classification)
        if decision is None:
            from app.policy.schemas import PolicyEvaluationContext
            engine = get_policy_engine()
            ctx = PolicyEvaluationContext(
                classification=norm_class,
                requested_provider=requested_provider,
                environment=environment or "cloud",
            )
            decision = engine.evaluate(ctx)

        return self.route(
            decision=decision,
            requested_provider=requested_provider,
            requested_model=requested_model,
            environment=environment,
        )

    def route(
        self,
        *,
        decision: PolicyDecision,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        environment: str | None = None,
    ) -> RouteDecision:
        """Resolve a compliant RouteDecision based on the PolicyEngine decision.

        Fails closed with a RouteDecision(allowed=False, error_code=...) if:
        - The policy decision itself was disallowed.
        - The requested provider is unknown to the registry.
        - The provider is incompatible with the policy decision's route.
        - A test/mock provider is requested in production.
        - The compliant provider is missing mandatory configuration/credentials.
        """
        env = (environment or settings.ENVIRONMENT or "development").strip().lower()
        is_production = env in _PRODUCTION_ENVIRONMENTS
        classification = decision.classification

        # 1. Respect PolicyEngine Authority: If PolicyEngine denied, router never overrides.
        if not decision.allowed:
            err_code = ERROR_POLICY_DENIED
            reason_lower = (decision.reason or "").lower()
            if "unknown" in reason_lower or self._registry.get_provider(requested_provider) is None:
                err_code = ERROR_UNKNOWN_PROVIDER
            elif "production" in reason_lower or (is_production and requested_provider in ("fake", "mock", "test", "dev")):
                err_code = ERROR_PRODUCTION_TEST_PROVIDER

            return RouteDecision(
                allowed=False,
                provider_id=requested_provider or "none",
                model_id=requested_model or "none",
                provider_category=ProviderCategory.UNKNOWN,
                processing_route=ProcessingRoute.BLOCKED,
                classification=classification,
                reason=f"Routing rejected by policy: {decision.reason}",
                error_code=err_code,
                details={"policy_reason": decision.reason},
            )

        # Parse authoritative route string into Enum
        try:
            target_route = ProcessingRoute(decision.processing_route)
        except ValueError:
            target_route = ProcessingRoute.BLOCKED

        if target_route == ProcessingRoute.BLOCKED:
            return RouteDecision(
                allowed=False,
                provider_id=requested_provider or "none",
                model_id=requested_model or "none",
                provider_category=ProviderCategory.UNKNOWN,
                processing_route=ProcessingRoute.BLOCKED,
                classification=classification,
                reason="Routing blocked: processing route is BLOCKED.",
                error_code=ERROR_POLICY_DENIED,
                details={"target_route": "blocked"},
            )

        # 2. Candidate Resolution: Determine requested or resolve compliant default
        descriptor: ProviderDescriptor | None = None
        if requested_provider:
            candidate_name = requested_provider
            descriptor = self._registry.get_provider(candidate_name)
            if descriptor is None:
                return RouteDecision(
                    allowed=False,
                    provider_id=candidate_name,
                    model_id=requested_model or "none",
                    provider_category=ProviderCategory.UNKNOWN,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason=f"Routing failure: Provider '{candidate_name}' is not recognized in the provider registry.",
                    error_code=ERROR_UNKNOWN_PROVIDER,
                    details={"requested_provider": candidate_name},
                )
        else:
            # 7. If no provider was explicitly requested, resolve a compliant configured
            # provider according to deterministic priority:
            candidates: list[str] = []
            if settings.LLM_PROVIDER:
                candidates.append(settings.LLM_PROVIDER)

            if target_route in (ProcessingRoute.CLOUD, ProcessingRoute.CONTROLLED_INTERNAL):
                candidates.extend(["openai", "gemini"])
            if target_route in (ProcessingRoute.PRIVATE_LOCAL, ProcessingRoute.CONTROLLED_INTERNAL):
                candidates.append("local")
            if not is_production:
                candidates.append("fake")

            for c in candidates:
                desc = self._registry.get_provider(c)
                if desc and _is_provider_configured(desc):
                    if target_route == ProcessingRoute.PRIVATE_LOCAL and desc.provider_category not in (
                        ProviderCategory.PRIVATE_LOCAL,
                        ProviderCategory.TEST_DEVELOPMENT,
                    ):
                        continue
                    if classification in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
                        if desc.provider_category == ProviderCategory.EXTERNAL_CLOUD:
                            continue
                    descriptor = desc
                    break

            if descriptor is None:
                return RouteDecision(
                    allowed=False,
                    provider_id="none",
                    model_id=requested_model or "none",
                    provider_category=ProviderCategory.UNKNOWN,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason="Routing failure: No compliant, configured provider is available for this route.",
                    error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                    details={"target_route": target_route.value, "classification": classification.value},
                )

        # 3. Production Test Provider Guardrail
        if descriptor.provider_category == ProviderCategory.TEST_DEVELOPMENT and is_production:
            return RouteDecision(
                allowed=False,
                provider_id=descriptor.provider_id,
                model_id=requested_model or descriptor.get_default_model(),
                provider_category=descriptor.provider_category,
                processing_route=ProcessingRoute.BLOCKED,
                classification=classification,
                reason="Routing failure: Test/mock provider cannot be used in production.",
                error_code=ERROR_PRODUCTION_TEST_PROVIDER,
                details={"provider_id": descriptor.provider_id, "environment": env},
            )

        # 4. Route Compatibility Check
        # PRIVATE_LOCAL route requires PRIVATE_LOCAL provider (or TEST_DEV in dev/test)
        if target_route == ProcessingRoute.PRIVATE_LOCAL:
            if descriptor.provider_category == ProviderCategory.EXTERNAL_CLOUD:
                return RouteDecision(
                    allowed=False,
                    provider_id=descriptor.provider_id,
                    model_id=requested_model or descriptor.get_default_model(),
                    provider_category=descriptor.provider_category,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason=f"Routing failure: {classification.value} material requires private/local route, but '{descriptor.provider_id}' is an external cloud provider.",
                    error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                    details={"provider_category": descriptor.provider_category.value},
                )
            if descriptor.provider_category not in (
                ProviderCategory.PRIVATE_LOCAL,
                ProviderCategory.TEST_DEVELOPMENT,
            ):
                return RouteDecision(
                    allowed=False,
                    provider_id=descriptor.provider_id,
                    model_id=requested_model or descriptor.get_default_model(),
                    provider_category=descriptor.provider_category,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason=f"Routing failure: Provider '{descriptor.provider_id}' is incompatible with route {target_route.value}.",
                    error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                    details={"target_route": target_route.value},
                )

        # CONTROLLED_INTERNAL route permits PRIVATE_LOCAL or controlled cloud (or test in dev)
        elif target_route == ProcessingRoute.CONTROLLED_INTERNAL:
            if descriptor.provider_category not in (
                ProviderCategory.PRIVATE_LOCAL,
                ProviderCategory.EXTERNAL_CLOUD,
                ProviderCategory.TEST_DEVELOPMENT,
            ):
                return RouteDecision(
                    allowed=False,
                    provider_id=descriptor.provider_id,
                    model_id=requested_model or descriptor.get_default_model(),
                    provider_category=descriptor.provider_category,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason=f"Routing failure: Provider '{descriptor.provider_id}' is incompatible with controlled internal route.",
                    error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                    details={"target_route": target_route.value},
                )

        # 5. Sensitive Data Safeguard: CONFIDENTIAL / RESTRICTED must NEVER be routed to EXTERNAL_CLOUD
        if classification in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
            if descriptor.provider_category == ProviderCategory.EXTERNAL_CLOUD:
                return RouteDecision(
                    allowed=False,
                    provider_id=descriptor.provider_id,
                    model_id=requested_model or descriptor.get_default_model(),
                    provider_category=descriptor.provider_category,
                    processing_route=ProcessingRoute.BLOCKED,
                    classification=classification,
                    reason=f"Routing failure: Sensitive data ({classification.value}) cannot be routed to external cloud provider '{descriptor.provider_id}'.",
                    error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                    details={"classification": classification.value},
                )

        # 6. Model Compatibility & Validation
        resolved_model = requested_model or settings.LLM_MODEL or descriptor.get_default_model()
        if requested_model and not descriptor.has_model(requested_model):
            # If the user requested an unsupported model for this provider, reject cleanly
            return RouteDecision(
                allowed=False,
                provider_id=descriptor.provider_id,
                model_id=requested_model,
                provider_category=descriptor.provider_category,
                processing_route=ProcessingRoute.BLOCKED,
                classification=classification,
                reason=f"Routing failure: Model '{requested_model}' is not supported by provider '{descriptor.provider_id}'.",
                error_code=ERROR_UNSUPPORTED_MODEL,
                details={
                    "requested_model": requested_model,
                    "supported_models": [m.model_id for m in descriptor.supported_models],
                },
            )

        # 7. Credential / Configuration Availability Check
        if not _is_provider_configured(descriptor):
            return RouteDecision(
                allowed=False,
                provider_id=descriptor.provider_id,
                model_id=resolved_model,
                provider_category=descriptor.provider_category,
                processing_route=ProcessingRoute.BLOCKED,
                classification=classification,
                reason=f"Routing failure: Compliant provider '{descriptor.provider_id}' is missing required configuration ({descriptor.env_key_variable or 'configuration'}).",
                error_code=ERROR_COMPLIANT_PROVIDER_UNAVAILABLE,
                details={
                    "missing_configuration": descriptor.env_key_variable,
                    "provider_id": descriptor.provider_id,
                },
            )

        # 8. Successful Compliant Route Resolution
        return RouteDecision(
            allowed=True,
            provider_id=descriptor.provider_id,
            model_id=resolved_model,
            provider_category=descriptor.provider_category,
            processing_route=descriptor.processing_route,
            classification=classification,
            reason=f"Compliant route established: {classification.value} data routed to {descriptor.provider_id} ({resolved_model}) via {descriptor.processing_route.value}.",
            error_code=None,
            details={
                "provider_id": descriptor.provider_id,
                "model_id": resolved_model,
                "route": descriptor.processing_route.value,
            },
        )


_DEFAULT_ROUTER = PolicyRouter()


def get_policy_router() -> PolicyRouter:
    """Return the global default PolicyRouter singleton."""
    return _DEFAULT_ROUTER
