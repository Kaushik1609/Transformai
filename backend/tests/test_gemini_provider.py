"""
Gemini LLM provider tests.

Verifies the ``LLM_PROVIDER=gemini`` integration:
- factory selection / fallback semantics;
- base-URL normalization for Google's OpenAI-compatible endpoint;
- credential safety (never echoed in repr/errors);
- mocked ``generate_text`` request shape / response handling (no network);
- the nested-object field hint added to common generator prompts.

These tests never make real network calls and never print/leak credentials.
A fake API key string is used ONLY to construct provider objects so wiring can
be asserted locally; it is never a real credential.
"""
import pytest

from app.core.config import Settings
from app.transformation.llm import (
    FakeLLMProvider,
    GeminiLLMProvider,
    build_llm_provider,
)


# ---------------------------------------------------------------------------
# Base URL normalization
# ---------------------------------------------------------------------------

class TestGeminiBaseUrlNormalization:
    def test_native_v1beta_appends_openai(self):
        from app.transformation.llm.gemini_provider import _normalize_gemini_base_url

        url = _normalize_gemini_base_url("https://generativelanguage.googleapis.com/v1beta")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_trailing_slash_native_appends_openai(self):
        from app.transformation.llm.gemini_provider import _normalize_gemini_base_url

        url = _normalize_gemini_base_url("https://generativelanguage.googleapis.com/v1beta/")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_full_openai_url_is_idempotent(self):
        from app.transformation.llm.gemini_provider import _normalize_gemini_base_url

        url = _normalize_gemini_base_url("https://generativelanguage.googleapis.com/v1beta/openai/")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_generic_v1_url_untouched(self):
        from app.transformation.llm.gemini_provider import _normalize_gemini_base_url

        url = _normalize_gemini_base_url("https://gateway.example.com/v1")
        assert url == "https://gateway.example.com/v1/"


# ---------------------------------------------------------------------------
# Construction / client wiring
# ---------------------------------------------------------------------------

class TestGeminiProviderConstruction:
    def test_native_base_url_is_normalized_on_client(self):
        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )
        assert provider._base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
        assert str(provider._client.base_url) == (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    def test_openai_url_preserved_on_client(self):
        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        assert str(provider._client.base_url) == (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    def test_model_configurable(self):
        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
        )
        assert provider._model == "gemini-3.6-flash"

    def test_credential_never_leaks_in_repr(self):
        secret = "ai-test-super-secret-not-real"
        provider = GeminiLLMProvider(
            api_key=secret,
            model="gemini-3.6-flash",
        )
        assert secret not in repr(provider)
        assert secret not in repr(provider._client)
        assert secret not in str(provider._client)

    def test_missing_api_key_raises_without_echoing_value(self):
        from app.core.config import settings

        saved_key = settings.LLM_API_KEY
        try:
            settings.LLM_API_KEY = ""
            with pytest.raises(ValueError) as exc:
                GeminiLLMProvider(api_key="", model="gemini-3.6-flash")
            assert "LLM_API_KEY" in str(exc.value)
        finally:
            settings.LLM_API_KEY = saved_key


# ---------------------------------------------------------------------------
# generate_text request shape / response handling (mocked)
# ---------------------------------------------------------------------------

class TestGeminiGenerateText:
    def test_sends_messages_and_json_object_format(self, monkeypatch):
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return None

        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

        # fake_create returns None -> generate_text must surface empty content.
        with pytest.raises(ValueError):
            provider.generate_text(system_prompt="sys", user_content="usr")

        assert captured["model"] == "gemini-3.6-flash"
        assert captured["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]
        assert captured["response_format"] == {"type": "json_object"}

    def test_returns_trimmed_content(self, monkeypatch):
        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
        )

        class FakeMessage:
            content = '  {"title": "Hi"}  '

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        monkeypatch.setattr(
            provider._client.chat.completions,
            "create",
            lambda **kw: FakeResponse(),
        )
        out = provider.generate_text(system_prompt="s", user_content="u")
        assert out == '{"title": "Hi"}'

    def test_empty_content_raises(self, monkeypatch):
        provider = GeminiLLMProvider(
            api_key="ai-test-not-real",
            model="gemini-3.6-flash",
        )

        class FakeMessage:
            content = None

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        monkeypatch.setattr(
            provider._client.chat.completions,
            "create",
            lambda **kw: FakeResponse(),
        )
        with pytest.raises(ValueError, match="empty"):
            provider.generate_text(system_prompt="s", user_content="u")


# ---------------------------------------------------------------------------
# Factory selection / fallback
# ---------------------------------------------------------------------------

class TestGeminiFactory:
    def test_selects_gemini_when_configured(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "gemini")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "ai-test-not-real")
        provider = build_llm_provider()
        assert isinstance(provider, GeminiLLMProvider)

    def test_explicit_gemini_arg_wins(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "ai-test-not-real")
        provider = build_llm_provider("gemini")
        assert isinstance(provider, GeminiLLMProvider)

    def test_falls_back_to_fake_without_key(self, monkeypatch):
        from app.transformation import llm as llm_mod

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_PROVIDER", "gemini")
        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "")
        provider = build_llm_provider()
        assert isinstance(provider, FakeLLMProvider)


class TestGeminiFallbackFactory:
    def test_gemini_fallback_requires_key(self, monkeypatch):
        from app.transformation import llm as llm_mod
        from app.transformation.llm.factory import _build_fallback_provider

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "")
        with pytest.raises(ValueError, match="requires LLM_API_KEY"):
            _build_fallback_provider("gemini")

    def test_gemini_fallback_with_key(self, monkeypatch):
        from app.transformation import llm as llm_mod
        from app.transformation.llm.factory import _build_fallback_provider

        monkeypatch.setattr(llm_mod.factory.settings, "LLM_API_KEY", "ai-test-not-real")
        provider = _build_fallback_provider("gemini")
        assert isinstance(provider, GeminiLLMProvider)


# ---------------------------------------------------------------------------
# Nested-object field hint in shared generator prompts
# ---------------------------------------------------------------------------

class TestGeminiNestedPromptHint:
    def test_presentation_nested_keys_are_specified(self):
        from app.transformation.generators.common import _typed_field_spec
        from app.transformation.output_schemas import PresentationStructure

        spec = _typed_field_spec(PresentationStructure)
        assert "slides:" in spec
        assert "EXACTLY these keys: title (string), key_message (string)" in spec
        assert "supporting_points (array of strings)" in spec

    def test_video_nested_keys_are_specified(self):
        from app.transformation.generators.common import _typed_field_spec
        from app.transformation.output_schemas import VideoPackage

        spec = _typed_field_spec(VideoPackage)
        assert "storyboard:" in spec
        assert "EXACTLY these keys: title (string), description (string), narration (string)" in spec

    def test_infographic_nested_keys_are_specified(self):
        from app.transformation.generators.common import _typed_field_spec
        from app.transformation.output_schemas import Infographic

        spec = _typed_field_spec(Infographic)
        assert "sections:" in spec
        assert "EXACTLY these keys: heading (string), message (string)" in spec
