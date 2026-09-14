"""
TransformIQ / KaryaSetu AI — Provider & Model Registry (Phase 2C)

Immutable descriptors defining supported AI providers, models, processing routes,
and configuration requirements.

The registry is deterministic, side-effect free, and makes no network calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.policy.schemas import ProcessingRoute, ProviderCategory


@dataclass(frozen=True)
class ModelDescriptor:
    """Descriptor for an AI model supported by a provider."""

    model_id: str
    display_name: str
    context_window: int = 4096
    default_temperature: float = 0.3


@dataclass(frozen=True)
class ProviderDescriptor:
    """Descriptor for an LLM provider and its policy/route characteristics."""

    provider_id: str
    provider_category: ProviderCategory
    processing_route: ProcessingRoute
    supported_models: tuple[ModelDescriptor, ...]
    is_production_ready: bool
    requires_credentials: bool
    env_key_variable: str | None = None
    env_base_url_variable: str | None = None
    env_model_variable: str | None = "LLM_MODEL"

    def has_model(self, model_id: str | None) -> bool:
        """Check if a specific model ID is recognized for this provider."""
        if not model_id:
            return True
        norm = model_id.strip().lower()
        return any(m.model_id.lower() == norm for m in self.supported_models)

    def get_default_model(self) -> str:
        """Return the default/primary model identifier for this provider."""
        if self.supported_models:
            return self.supported_models[0].model_id
        return "default"

    @property
    def requires_credential(self) -> bool:
        """Alias for requires_credentials."""
        return self.requires_credentials



# ---------------------------------------------------------------------------
# Canonical Provider & Model Profiles
# ---------------------------------------------------------------------------

OPENAI_MODELS = (
    ModelDescriptor(model_id="gpt-4o-mini", display_name="GPT-4o Mini", context_window=128000),
    ModelDescriptor(model_id="gpt-4o", display_name="GPT-4o", context_window=128000),
    ModelDescriptor(model_id="gpt-3.5-turbo", display_name="GPT-3.5 Turbo", context_window=16385),
)

GEMINI_MODELS = (
    ModelDescriptor(model_id="gemini-2.5-flash", display_name="Gemini 2.5 Flash", context_window=1000000),
    ModelDescriptor(model_id="gemini-1.5-pro", display_name="Gemini 1.5 Pro", context_window=2000000),
    ModelDescriptor(model_id="gemini-1.5-flash", display_name="Gemini 1.5 Flash", context_window=1000000),
    ModelDescriptor(model_id="gemini-3.6-flash", display_name="Gemini 3.6 Flash", context_window=1000000),
)

LOCAL_MODELS = (
    ModelDescriptor(model_id="llama-3-8b", display_name="Llama 3 8B (On-Premises)", context_window=8192),
    ModelDescriptor(model_id="mistral-7b", display_name="Mistral 7B (On-Premises)", context_window=32768),
    ModelDescriptor(model_id="qwen-7b", display_name="Qwen 7B (On-Premises)", context_window=32768),
    ModelDescriptor(model_id="local-default", display_name="Local LLM Engine", context_window=8192),
)

FAKE_MODELS = (
    ModelDescriptor(model_id="deterministic-fake", display_name="Deterministic Fake Generator", context_window=4096),
)

# Immutable catalog of canonical descriptors
_PROVIDER_CATALOG: dict[str, ProviderDescriptor] = {
    "openai": ProviderDescriptor(
        provider_id="openai",
        provider_category=ProviderCategory.EXTERNAL_CLOUD,
        processing_route=ProcessingRoute.CLOUD,
        supported_models=OPENAI_MODELS,
        is_production_ready=True,
        requires_credentials=True,
        env_key_variable="LLM_API_KEY",
        env_base_url_variable="LLM_BASE_URL",
    ),
    "gemini": ProviderDescriptor(
        provider_id="gemini",
        provider_category=ProviderCategory.EXTERNAL_CLOUD,
        processing_route=ProcessingRoute.CLOUD,
        supported_models=GEMINI_MODELS,
        is_production_ready=True,
        requires_credentials=True,
        env_key_variable="LLM_API_KEY",
        env_base_url_variable="LLM_BASE_URL",
    ),
    "local": ProviderDescriptor(
        provider_id="local",
        provider_category=ProviderCategory.PRIVATE_LOCAL,
        processing_route=ProcessingRoute.PRIVATE_LOCAL,
        supported_models=LOCAL_MODELS,
        is_production_ready=True,
        requires_credentials=False,
        env_key_variable=None,
        env_base_url_variable="LLM_BASE_URL",
    ),
    "ollama": ProviderDescriptor(
        provider_id="ollama",
        provider_category=ProviderCategory.PRIVATE_LOCAL,
        processing_route=ProcessingRoute.PRIVATE_LOCAL,
        supported_models=LOCAL_MODELS,
        is_production_ready=True,
        requires_credentials=False,
        env_key_variable=None,
        env_base_url_variable="LLM_BASE_URL",
    ),
    "vllm": ProviderDescriptor(
        provider_id="vllm",
        provider_category=ProviderCategory.PRIVATE_LOCAL,
        processing_route=ProcessingRoute.PRIVATE_LOCAL,
        supported_models=LOCAL_MODELS,
        is_production_ready=True,
        requires_credentials=False,
        env_key_variable=None,
        env_base_url_variable="LLM_BASE_URL",
    ),
    "fake": ProviderDescriptor(
        provider_id="fake",
        provider_category=ProviderCategory.TEST_DEVELOPMENT,
        processing_route=ProcessingRoute.CONTROLLED_INTERNAL,
        supported_models=FAKE_MODELS,
        is_production_ready=False,
        requires_credentials=False,
        env_key_variable=None,
        env_base_url_variable=None,
    ),
}

# Alias map mapping variants / prefixes to canonical provider IDs
_PROVIDER_ALIASES: dict[str, str] = {
    "azure": "openai",
    "azure_openai": "openai",
    "private": "local",
    "on_prem": "local",
    "on_premises": "local",
    "self_hosted": "local",
    "mock": "fake",
    "test": "fake",
    "dev": "fake",
    "development": "fake",
    "development (fake - testing purpose)": "fake",
}


class ProviderRegistry:
    """In-memory registry providing deterministic descriptor lookups."""

    def __init__(self, catalog: Mapping[str, ProviderDescriptor] | None = None) -> None:
        self._catalog: dict[str, ProviderDescriptor] = dict(catalog or _PROVIDER_CATALOG)

    def get_provider(self, provider_id: str | None) -> ProviderDescriptor | None:
        """Resolve a provider identifier (including aliases) to its descriptor."""
        if not provider_id:
            return None
        clean = str(provider_id).strip().lower()
        canonical_id = _PROVIDER_ALIASES.get(clean, clean)
        if canonical_id in self._catalog:
            return self._catalog[canonical_id]

        # Check prefix matching for names like 'openai/gpt-4o' or 'local:llama-3'
        if "/" in clean:
            prefix = clean.split("/", 1)[0]
            canonical_prefix = _PROVIDER_ALIASES.get(prefix, prefix)
            if canonical_prefix in self._catalog:
                return self._catalog[canonical_prefix]
        if ":" in clean:
            prefix = clean.split(":", 1)[0]
            canonical_prefix = _PROVIDER_ALIASES.get(prefix, prefix)
            if canonical_prefix in self._catalog:
                return self._catalog[canonical_prefix]

        return None

    def list_providers(self) -> list[ProviderDescriptor]:
        """Return all registered providers in deterministic order."""
        return sorted(self._catalog.values(), key=lambda p: p.provider_id)

    def get_providers_for_route(self, route: ProcessingRoute) -> list[ProviderDescriptor]:
        """Return all providers compatible with a given processing route."""
        return [p for p in self.list_providers() if p.processing_route == route]

    def get_model(self, provider_id: str | None, model_id: str | None) -> ModelDescriptor | None:
        """Resolve a specific model descriptor for a given provider."""
        provider = self.get_provider(provider_id)
        if not provider or not model_id:
            return None
        clean_model = model_id.strip().lower()
        for m in provider.supported_models:
            if m.model_id.lower() == clean_model:
                return m
        return None


_DEFAULT_REGISTRY = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    """Return the global default ProviderRegistry singleton."""
    return _DEFAULT_REGISTRY
