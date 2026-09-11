"""Phase 11J-A — Provider configuration and transformation output-type contracts.

Pins the hardened contracts delivered in 11J-A:

- ``TransformationJobCreate.output_types`` accepts exactly the seven supported
  types (summary, linkedin, advisory, presentation, x, infographic, video) and
  rejects anything else at schema/request validation time with a normal
  Pydantic/FastAPI 422 error.
- LLM provider selection is explicit: ``fake`` needs no credentials, while
  ``openai``/``gemini`` REQUIRE ``LLM_API_KEY`` and fail clearly when it is
  missing instead of silently falling back to ``FakeLLMProvider``.
- Embedding provider selection is explicit too: ``fake`` works offline and
  ``openai`` without ``EMBEDDING_API_KEY`` fails clearly (never a silent fake).
- ``ProviderManager`` remains the sole retry/resilience owner.
- Configuration errors never contain credential values.
- Existing generator/transformation behavior with injected providers is
  preserved.

All tests are deterministic and offline; no live API calls.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.schemas.transformation import TransformationJobCreate
from app.embeddings.fake import FakeEmbeddingProvider
from app.transformation.generators import KNOWN_OUTPUT_TYPES, get_generator
from app.transformation.llm import (
    FakeLLMProvider,
    build_llm_provider,
    build_resilient_provider,
)
from app.transformation.llm import factory as llm_factory
from app.transformation.llm.gemini_provider import GeminiLLMProvider
from app.transformation.llm.openai_provider import OpenAILLMProvider
from app.transformation.llm.resilience import ProviderManager
from app.transformation.output_schemas.parser import parse_output


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

REQUIRED_SEVEN = frozenset(
    {"summary", "linkedin", "advisory", "presentation", "x", "infographic", "video"}
)

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary with key facts.",
    "topics": [{"value": "technology"}],
    "entities": [{"name": "Acme Corp"}],
    "key_points": [
        {"text": "First key point", "source_chunk_ids": []},
        {"text": "Second key point", "source_chunk_ids": []},
    ],
    "claims": [{"text": "A source claim", "source_chunk_ids": []}],
    "statistics": [{"text": "37% of respondents", "source_chunk_ids": []}],
    "dates": [{"text": "2024"}],
    "recommendations": [{"text": "Recommended action", "source_chunk_ids": []}],
    "source_references": [{"text": "Source reference A", "source_chunk_ids": []}],
}

CONFIG: dict[str, Any] = {
    "target_audience": "Executives",
    "tone": "professional",
    "language": "English",
    "detail_level": "standard",
    "communication_objective": "decision support",
}


def _job_payload(output_types: list[str]) -> dict[str, str]:
    return {
        "project_id": str(uuid.uuid4()),
        "source_id": str(uuid.uuid4()),
        "configuration_id": str(uuid.uuid4()),
        "output_types": output_types,
    }


# ---------------------------------------------------------------------------
# 1. output_types strong validation (schema + request boundary)
# ---------------------------------------------------------------------------


def test_known_output_types_registry_matches_seven_type_contract():
    """The registry remains the single source of truth for the 7 types."""
    assert set(KNOWN_OUTPUT_TYPES) == REQUIRED_SEVEN
    assert len(KNOWN_OUTPUT_TYPES) == 7


def test_all_seven_output_types_accepted_by_request_schema():
    ordered = sorted(REQUIRED_SEVEN)
    job = TransformationJobCreate(**_job_payload(ordered))
    assert list(job.output_types) == ordered


def test_ordering_and_duplicates_preserved():
    job = TransformationJobCreate(**_job_payload(["summary", "summary", "video"]))
    assert list(job.output_types) == ["summary", "summary", "video"]


def test_unsupported_output_type_rejected():
    with pytest.raises(ValidationError) as exc:
        TransformationJobCreate(**_job_payload(["summary", "not-a-type"]))
    body = str(exc.value)
    assert "Unsupported output type" in body
    assert "'not-a-type'" in body


def test_multiple_unknown_types_reported_with_supported_list():
    with pytest.raises(ValidationError) as exc:
        TransformationJobCreate(**_job_payload(["gif", "png"]))
    body = str(exc.value)
    for unknown in ("gif", "png"):
        assert repr(unknown) in body
    for supported in ("summary", "advisory", "video"):
        assert supported in body


def test_empty_output_types_rejected():
    with pytest.raises(ValidationError):
        TransformationJobCreate(**_job_payload([]))


def test_api_rejects_unknown_output_type_with_standard_422():
    probe = FastAPI()

    @probe.post("/transformations/_probe")
    def _probe(body: TransformationJobCreate):
        return {"accepted": list(body.output_types)}

    client = TestClient(probe)
    resp = client.post("/transformations/_probe", json=_job_payload(["summary", "nope"]))
    assert resp.status_code == 422
    detail = resp.json()["detail"][0]
    assert detail["type"] == "value_error"
    assert "output_types" in detail["loc"]


def test_api_accepts_valid_output_types():
    probe = FastAPI()

    @probe.post("/transformations/_probe")
    def _probe(body: TransformationJobCreate):
        return {"accepted": list(body.output_types)}

    client = TestClient(probe)
    resp = client.post(
        "/transformations/_probe", json=_job_payload(sorted(REQUIRED_SEVEN))
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] == sorted(REQUIRED_SEVEN)


# ---------------------------------------------------------------------------
# 2. LLM provider selection contract
# ---------------------------------------------------------------------------


def test_llm_fake_explicit_requires_no_key(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "fake")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "")
    provider = build_llm_provider()
    assert isinstance(provider, FakeLLMProvider)


def test_llm_openai_missing_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        build_llm_provider()


def test_llm_gemini_missing_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        build_llm_provider()


def test_llm_openai_with_key_never_silently_fake(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "sk-test-not-real")
    provider = build_llm_provider()
    assert isinstance(provider, OpenAILLMProvider)


def test_llm_gemini_with_key_never_silently_fake(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "ai-test-not-real")
    provider = build_llm_provider()
    assert isinstance(provider, GeminiLLMProvider)


def test_llm_unsupported_provider_fails(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "not-a-provider")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "sk-test-not-real")
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        build_llm_provider()


def test_llm_config_errors_never_echo_credential_values(monkeypatch):
    secret = "sk-super-secret-value-that-must-not-leak"
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "   ")
    with pytest.raises(ValueError) as exc:
        build_llm_provider()
    message = str(exc.value)
    assert secret not in message
    assert "sk-" not in message
    assert "LLM_API_KEY" in message


# ---------------------------------------------------------------------------
# 3. Embedding provider selection contract
# ---------------------------------------------------------------------------


def test_embedding_fake_works_offline():
    from app.embeddings.factory import build_embedding_provider

    provider = build_embedding_provider("fake")
    assert isinstance(provider, FakeEmbeddingProvider)


def test_embedding_openai_missing_key_fails_clearly(monkeypatch):
    from app.embeddings import factory as emb_factory
    from app.embeddings.factory import build_embedding_provider

    monkeypatch.setattr(emb_factory.settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(emb_factory.settings, "EMBEDDING_API_KEY", "")
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY"):
        build_embedding_provider()


def test_embedding_config_errors_never_echo_credential_values(monkeypatch):
    from app.embeddings import factory as emb_factory
    from app.embeddings.factory import build_embedding_provider

    secret = "sk-embedding-secret-that-must-not-leak"
    monkeypatch.setattr(emb_factory.settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(emb_factory.settings, "EMBEDDING_API_KEY", "")
    with pytest.raises(ValueError) as exc:
        build_embedding_provider()
    message = str(exc.value)
    assert secret not in message
    assert "sk-" not in message
    assert "EMBEDDING_API_KEY" in message


# ---------------------------------------------------------------------------
# 4. ProviderManager stays the retry/resilience owner
# ---------------------------------------------------------------------------


def test_providermanager_wraps_fake_without_live_calls(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "fake")
    manager = build_resilient_provider()
    assert isinstance(manager, ProviderManager)
    assert isinstance(manager.primary, FakeLLMProvider)


def test_providermanager_wraps_real_provider_when_configured(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "ai-test-not-real")
    monkeypatch.setattr(llm_factory.settings, "LLM_FALLBACK_PROVIDER", "")
    manager = build_resilient_provider()
    assert isinstance(manager, ProviderManager)
    assert isinstance(manager.primary, GeminiLLMProvider)


# ---------------------------------------------------------------------------
# 5. Provider injection + existing transformation generation compatibility
# ---------------------------------------------------------------------------


def test_explicit_injection_returns_requested_provider(monkeypatch):
    monkeypatch.setattr(llm_factory.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm_factory.settings, "LLM_API_KEY", "sk-test-not-real")
    provider = build_llm_provider("fake")
    assert isinstance(provider, FakeLLMProvider)


@pytest.mark.parametrize("output_type", sorted(REQUIRED_SEVEN))
def test_all_seven_types_still_generate_offline_with_fake(output_type):
    generator = get_generator(output_type, llm_provider=FakeLLMProvider())
    assert generator is not None
    out = generator.generate(canonical=CANONICAL, config=CONFIG)
    assert isinstance(out.get("text"), str) and out["text"].strip()
    parse_output(output_type, json.dumps(out))