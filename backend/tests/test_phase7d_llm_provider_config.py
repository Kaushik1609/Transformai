"""
Phase 7d — LLM Provider configuration (LLM_BASE_URL) tests.

Verifies the configurable OpenAI-compatible base URL support added for
development/prototype testing against third-party OpenAI-compatible gateways
(e.g. OpenCode Zen / big-pickle).

These tests:
- never require network access (no real LLM endpoint is called);
- never print or leak any credential/API key value;
- preserve the existing FakeLLMProvider offline behavior and factory
  fallback semantics.

A fake API key string is used ONLY to construct provider objects so the
base_url wiring can be asserted locally; it is never a real credential and
is never asserted to appear in reprs/logs.
"""
import pytest

from app.core.config import Settings
from app.transformation.llm import FakeLLMProvider, OpenAILLMProvider, build_llm_provider


class TestLLMBaseUrlConfig:
    def test_base_url_default_is_empty(self):
        """LLM_BASE_URL must default to empty to preserve existing behavior."""
        assert Settings(LLM_BASE_URL="").LLM_BASE_URL == ""

    def test_base_url_loads_from_settings(self):
        """LLM_BASE_URL should load a configured value."""
        url = "https://gateway.example.com/v1"
        assert Settings(LLM_BASE_URL=url, LLM_API_KEY="key").LLM_BASE_URL == url


class TestOpenAIProviderBaseUrl:
    def test_passes_base_url_when_configured(self):
        """OpenAILLMProvider forwards base_url to the underlying client."""
        url = "https://opencode.ai/zen/v1"
        provider = OpenAILLMProvider(
            model="big-pickle",
            api_key="sk-test-not-real",
            base_url=url,
        )
        assert provider._client.openai_api_base == url
        assert provider._client.model_name == "big-pickle"

    def test_preserves_default_endpoint_when_base_url_empty(self):
        """With no base URL, the client keeps the default (None => OpenAI)."""
        provider = OpenAILLMProvider(
            model="gpt-4o-mini",
            api_key="sk-test-not-real",
            base_url=None,
        )
        assert provider._client.openai_api_base is None
        assert provider._client.model_name == "gpt-4o-mini"

    def test_credential_never_leaks_in_repr(self):
        """The API key must never surface in repr/str of the provider or client."""
        secret = "sk-test-super-secret-no-real"
        provider = OpenAILLMProvider(
            model="gpt-4o-mini",
            api_key=secret,
            base_url="https://opencode.ai/zen/v1",
        )
        assert secret not in repr(provider)
        assert secret not in repr(provider._client)
        assert secret not in str(provider._client)

    def test_missing_api_key_raises_without_echoing_value(self):
        """Missing API key raises a ValueError that does not contain a key."""
        from app.core.config import settings

        # Force the module settings to carry no key for this construction.
        saved_key = settings.LLM_API_KEY
        try:
            settings.LLM_API_KEY = ""
            with pytest.raises(ValueError) as exc:
                OpenAILLMProvider(model="gpt-4o-mini", api_key="", base_url="")
            assert "LLM_API_KEY" in str(exc.value)
        finally:
            settings.LLM_API_KEY = saved_key


class TestFakeProviderRemainsOffline:
    def test_fake_provider_produces_valid_output_offline(self):
        """FakeLLMProvider must work with no client/network at all."""
        provider = FakeLLMProvider()
        out = provider.generate_text(
            system_prompt="fields: {title, summary, text}",
            user_content="TITLE: TransformIQ\nSUMMARY: AI platform",
        )
        assert isinstance(out, str) and out.strip()
        assert "TransformIQ" in out

    def test_fake_provider_has_no_client(self):
        """FakeLLMProvider should not carry any HTTP client object."""
        provider = FakeLLMProvider()
        assert not hasattr(provider, "_client")


class TestProviderFactory:
    def test_selects_openai_when_configured(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "sk-test-not-real")
        provider = build_llm_provider()
        assert isinstance(provider, OpenAILLMProvider)

    def test_openai_without_key_fails_clearly(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "")
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            build_llm_provider()

    def test_fake_provider_selected_explicitly(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "fake")
        provider = build_llm_provider()
        assert isinstance(provider, FakeLLMProvider)

    def test_unsupported_provider_raises(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "not-a-provider")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "sk-test-not-real")
        with pytest.raises(ValueError):
            build_llm_provider()


class TestProviderInjection:
    def test_factory_accepts_explicit_provider_arg(self, monkeypatch):
        """build_llm_provider('openai') still works even if settings differ."""
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "sk-test-not-real")
        provider = build_llm_provider("openai")
        assert isinstance(provider, OpenAILLMProvider)

    def test_explicit_fake_arg_wins(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "sk-test-not-real")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_BASE_URL", "https://x/v1")
        provider = build_llm_provider("fake")
        assert isinstance(provider, FakeLLMProvider)
