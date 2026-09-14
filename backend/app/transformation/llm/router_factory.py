"""
TransformIQ / KaryaSetu AI — Compliant Router Factory (Phase 2C)

Converts a verified RouteDecision into an authoritative LLMProvider instance.
Adheres strictly to the following contracts:
- Reuses existing OpenAILLMProvider, GeminiLLMProvider, and FakeLLMProvider.
- For private/local providers, initializes with existing LLM_BASE_URL.
- Never injects cloud fallback for sensitive classifications (CONFIDENTIAL / RESTRICTED).
- Fallbacks must pass through policy validation before instantiation.
- Never exposes secrets, keys, or passwords.
"""
from __future__ import annotations

from app.core.config import settings
from app.policy.classification import InformationClassification
from app.policy.schemas import ProcessingRoute, ProviderCategory, RouteDecision
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.gemini_provider import GeminiLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.llm.resilience import ProviderManager, RetryPolicy


class CompliantRoutingError(ValueError):
    """Raised when a compliant LLM provider cannot be instantiated or is unavailable."""


def build_routed_llm_provider(
    route_decision: RouteDecision,
    *,
    resilient: bool = True,
    environment: str | None = None,
) -> LLMProvider:
    """Instantiate the concrete LLMProvider mandated by a RouteDecision.

    Raises:
        CompliantRoutingError: If the decision was not allowed or required configuration is missing.
    """
    if not route_decision.allowed:
        raise CompliantRoutingError(
            f"Cannot build provider for denied route: {route_decision.reason}"
        )

    provider_id = route_decision.provider_id.strip().lower()
    model_id = route_decision.model_id
    classification = route_decision.classification

    # Strict sensitive data safety check
    if classification in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
        if route_decision.provider_category == ProviderCategory.EXTERNAL_CLOUD:
            raise CompliantRoutingError(
                f"Sensitive data ({classification.value}) cannot be bound to cloud provider '{provider_id}'."
            )

    # 1. Instantiate base provider
    base_provider: LLMProvider
    if provider_id == "fake":
        base_provider = FakeLLMProvider()
    elif provider_id in ("local", "ollama", "vllm"):
        base_url = (settings.LLM_BASE_URL or "").strip()
        if not base_url:
            raise CompliantRoutingError(
                "COMPLIANT_PROVIDER_UNAVAILABLE: Local provider requires LLM_BASE_URL to be configured."
            )
        dummy_or_local_key = (settings.LLM_API_KEY or "").strip() or "local-no-key-required"
        base_provider = OpenAILLMProvider(
            model=model_id,
            api_key=dummy_or_local_key,
            base_url=base_url,
        )
    elif provider_id == "openai":
        api_key = (settings.LLM_API_KEY or "").strip()
        if not api_key:
            raise CompliantRoutingError(
                "COMPLIANT_PROVIDER_UNAVAILABLE: OpenAI provider requires LLM_API_KEY."
            )
        base_provider = OpenAILLMProvider(model=model_id, api_key=api_key)
    elif provider_id == "gemini":
        api_key = (settings.LLM_API_KEY or "").strip()
        if not api_key:
            raise CompliantRoutingError(
                "COMPLIANT_PROVIDER_UNAVAILABLE: Gemini provider requires LLM_API_KEY."
            )
        base_provider = GeminiLLMProvider(model=model_id, api_key=api_key)
    else:
        raise CompliantRoutingError(
            f"UNKNOWN_PROVIDER: Provider '{provider_id}' is unsupported by the runtime factory."
        )

    if not resilient:
        return base_provider

    # 2. Wrap in ProviderManager with Compliant Fallback Checking
    # Sensitive data (CONFIDENTIAL / RESTRICTED) must NEVER have cloud fallbacks!
    fallback: LLMProvider | None = None
    if classification not in (InformationClassification.CONFIDENTIAL, InformationClassification.RESTRICTED):
        fallback_name = (settings.LLM_FALLBACK_PROVIDER or "").strip().lower()
        if fallback_name and fallback_name != provider_id:
            try:
                if fallback_name == "fake":
                    fallback = FakeLLMProvider()
                elif fallback_name == "openai" and (settings.LLM_API_KEY or "").strip():
                    fallback = OpenAILLMProvider(api_key=settings.LLM_API_KEY)
                elif fallback_name == "gemini" and (settings.LLM_API_KEY or "").strip():
                    fallback = GeminiLLMProvider(api_key=settings.LLM_API_KEY)
            except Exception:
                fallback = None

    return ProviderManager(
        base_provider,
        fallback=fallback,
        max_attempts=settings.LLM_RETRY_MAX_ATTEMPTS,
        retry_policy=RetryPolicy(
            base_delay=settings.LLM_RETRY_BASE_DELAY,
            max_delay=settings.LLM_RETRY_MAX_DELAY,
            jitter=settings.LLM_RETRY_JITTER,
            max_429_wait=settings.LLM_RETRY_MAX_429_WAIT,
        ),
    )


def instantiate_routed_provider(route_decision: RouteDecision) -> LLMProvider:
    """Instantiate the raw base LLMProvider without resilience wrappers."""
    return build_routed_llm_provider(route_decision, resilient=False)

