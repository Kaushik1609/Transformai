"""Phase 7 — Output Generators tests.

Covers the LLM-powered, schema-validated generators for all 7 output types:
summary, linkedin, advisory, presentation, x, infographic, video.  Uses the
deterministic FakeLLMProvider (no external LLM API) plus verified rendering to
a real PPTX artifact.  Also verifies that the deterministic Phase 6 fallback
(no injected provider) is preserved for summary/linkedin/advisory.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.ingestion.storage import LocalStorage
from app.rag.schemas import RAGContext
from app.transformation.artifacts import output_storage_key
from app.transformation.generators import (
    KNOWN_OUTPUT_TYPES,
    AdvisoryGenerator,
    InfographicGenerator,
    LinkedInGenerator,
    PresentationGenerator,
    SummaryGenerator,
    VideoGenerator,
    XGenerator,
    get_generator,
    supported_output_types,
)
from app.transformation.llm import FakeLLMProvider, LLMProvider
from app.transformation.output_schemas import ALL_OUTPUT_SCHEMAS
from app.transformation.output_schemas.parser import OutputSchemaError, parse_output
from app.transformation.render.pptx import (
    PPTX_MIME_TYPE,
    parse_pptx,
    render_presentation,
)
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

CANONICAL: dict[str, Any] = {
    "id": str(uuid.uuid4()),
    "source_id": str(uuid.uuid4()),
    "title": "Test Source",
    "summary": "A test source summary.",
    "topics": [{"value": "technology"}],
    "entities": [{"name": "Acme Corp"}],
    "key_points": [
        {"text": "First key point", "source_chunk_ids": []},
        {"text": "Second key point", "source_chunk_ids": []},
    ],
    "claims": [{"text": "A source claim", "source_chunk_ids": []}],
    "statistics": [{"text": "37% of respondents", "source_chunk_ids": []}],
    "dates": [],
    "recommendations": [{"text": "Recommended action", "source_chunk_ids": []}],
    "source_references": [],
}

CONFIG: dict[str, Any] = {
    "target_audience": "Executives",
    "tone": "professional",
    "language": "English",
    "detail_level": "standard",
}

ALL_7 = ["advisory", "infographic", "linkedin", "presentation", "summary", "video", "x"]


def make_db(with_canonical: bool = True):
    """In-memory sqlite seeded with a ready project/source/canonical."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"p7-{uuid.uuid4().hex}@example.test", name="P7", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 7")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line one.\nSource line two.",
        )
        db.add_all([user, project, source])
        db.flush()
        if with_canonical:
            db.add(CanonicalContent(
                id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
                title=CANONICAL["title"], summary=CANONICAL["summary"],
                key_points=[{"text": "First key point", "source_chunk_ids": []}],
                recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            ))
        db.commit()
    return engine, project.id, source.id


def add_job(engine, project_id: uuid.UUID, source_id: uuid.UUID, output_types: list[str]) -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as db:
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=cfg.id,
            requested_outputs={"output_types": output_types}, status="queued",
        )
        db.add(job)
        db.commit()
        return job.id


class RecordingProvider(LLMProvider):
    """A stub provider that records the prompt inputs it is given.

    Used to assert that generators forward canonical + RAG context into the
    user-content prompt (source grounding) while returning a valid payload.
    """

    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        self.recorded.append((system_prompt, user_content))
        return json.dumps({
            "title": "Test Source",
            "summary": "A test source summary.",
            "key_findings": ["First key point"],
            "recommendations": ["Recommended action"],
            "text": "# Test Source\n\nA test source summary.",
        })


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_supported_output_types_is_exactly_seven():
    assert supported_output_types() == ALL_7


def test_known_output_types_is_frozenset():
    assert isinstance(KNOWN_OUTPUT_TYPES, frozenset)
    assert len(KNOWN_OUTPUT_TYPES) == 7
    assert set(KNOWN_OUTPUT_TYPES) == set(ALL_7)


def test_registry_matches_schema_discriminators():
    assert set(supported_output_types()) == set(ALL_OUTPUT_SCHEMAS)


def test_get_generator_returns_generator_for_every_type():
    for output_type in ALL_7:
        gen = get_generator(output_type)
        assert gen is not None, output_type
        assert gen.output_type == output_type


def test_get_generator_returns_none_for_unknown_type():
    assert get_generator("does-not-exist") is None


def test_get_generator_injects_llm_provider():
    fake = FakeLLMProvider()
    gen = get_generator("summary", llm_provider=fake)
    assert gen is not None
    assert gen.llm_provider is fake


# ---------------------------------------------------------------------------
# Generator unit tests (LLM path, FakeLLMProvider)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("output_type", ALL_7)
def test_generator_produces_valid_nonempty_output(output_type):
    gen = get_generator(output_type, llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    # Non-empty human text (required by the validate stage).
    assert isinstance(out.get("text"), str)
    assert out["text"].strip()
    # Must validate against the output's schema.
    validated = parse_output(output_type, json.dumps(out))  # raises on invalid
    assert validated.type == output_type
    assert validated.title.strip()


@pytest.mark.parametrize("output_type", ALL_7)
def test_generator_output_grounded_in_source(output_type):
    gen = get_generator(output_type, llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    blob = json.dumps(out)
    # The title must survive into the structured output (source grounding).
    assert "Test Source" in blob


def test_generate_without_provider_yields_valid_output():
    """The FakeLLMProvider default means offline generators still validate."""
    for output_type in ("presentation", "x", "infographic", "video"):
        gen = get_generator(output_type, llm_provider=None)
        out = gen.generate(canonical=CANONICAL, config=CONFIG)
        parse_output(output_type, json.dumps(out))


def test_summary_rag_grounding_via_user_content():
    rag = RAGContext(
        query="test",
        assembled_text="RAG chunk evidence for grounding",
        chunk_count=1,
        citations=[],
    )
    provider = RecordingProvider()
    gen = SummaryGenerator(llm_provider=provider)
    gen.generate(canonical=CANONICAL, config=CONFIG, rag_context=rag)
    assert provider.recorded
    _, user_content = provider.recorded[0]
    assert "Test Source" in user_content
    assert "First key point" in user_content
    # RAG assembled text is forwarded so the model is source-grounded.
    assert "RAG chunk evidence for grounding" in user_content


# ---------------------------------------------------------------------------
# Deterministic Phase 6 fallback preservation
# ---------------------------------------------------------------------------

def test_deterministic_summary_fallback_preserved():
    gen = SummaryGenerator(llm_provider=None)
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert "# Executive Summary: Test Source" in out["text"]
    assert "First key point" in out["text"]
    assert "Recommended action" in out["text"]


def test_deterministic_linkedin_fallback_preserved():
    gen = LinkedInGenerator(llm_provider=None)
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert "Just published: Test Source" in out["text"]
    assert "First key point" in out["text"]


def test_deterministic_advisory_fallback_preserved():
    gen = AdvisoryGenerator(llm_provider=None)
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert "# Advisory: Test Source" in out["text"]
    assert "## Situation" in out["text"]
    assert "Recommended action" in out["text"]


# ---------------------------------------------------------------------------
# Output structure specifics
# ---------------------------------------------------------------------------

def test_presentation_structure_and_real_pptx():
    gen = PresentationGenerator(llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert isinstance(out.get("slides"), list)
    assert len(out["slides"]) >= 1
    slide = out["slides"][0]
    assert slide["title"]
    assert slide["key_message"]

    pptx_bytes = render_presentation(parse_output("presentation", json.dumps(out)))
    assert isinstance(pptx_bytes, bytes)
    assert len(pptx_bytes) > 1000
    prs = parse_pptx(pptx_bytes)
    assert len(prs.slides) >= 1


def test_x_output_has_thread_structure():
    gen = XGenerator(llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert isinstance(out.get("thread"), list)
    assert len(out["thread"]) >= 1
    for post in out["thread"]:
        assert isinstance(post, str) and post.strip()


def test_infographic_has_sections():
    gen = InfographicGenerator(llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert isinstance(out.get("sections"), list)
    assert len(out["sections"]) >= 1
    section = out["sections"][0]
    assert section["heading"]
    assert section["message"]
    assert out.get("layout_recommendation")
    assert out.get("key_messages")


def test_video_package_has_storyboard():
    gen = VideoGenerator(llm_provider=FakeLLMProvider())
    out = gen.generate(canonical=CANONICAL, config=CONFIG)
    assert isinstance(out.get("storyboard"), list)
    assert len(out["storyboard"]) >= 1
    scene = out["storyboard"][0]
    assert scene["title"]
    assert scene["narration"]
    assert scene["subtitle"]
    assert out.get("script")
    assert out.get("narration_full")


def test_output_schema_rejects_invalid_payload():
    with pytest.raises(OutputSchemaError):
        parse_output("summary", json.dumps({"title": ""}))


# ---------------------------------------------------------------------------
# End-to-end job execution with provider + storage
# ---------------------------------------------------------------------------

def test_multi_output_job_with_provider_and_storage(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id = add_job(engine, project_id, source_id, ALL_7)

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] >= 1
    assert result["outputs_failed"] == 0

    with Session(engine, expire_on_commit=False) as db:
        outputs = db.execute(select(Output)).scalars().all()
        assert {o.output_type for o in outputs} == set(ALL_7)
        for o in outputs:
            assert o.status == "completed"
            assert o.output_metadata.get("provider") == "phase7"
            assert o.text_content.strip()

        pres = next(o for o in outputs if o.output_type == "presentation")
        assert pres.mime_type == PPTX_MIME_TYPE
        assert pres.storage_key
        expected_key = output_storage_key(project_id, job_id, pres.id, PPTX_MIME_TYPE)
        assert pres.storage_key == expected_key
        # The artifact bytes actually land under the storage root.
        artifact = storage.read(pres.storage_key)
        assert isinstance(artifact, bytes)
        assert len(artifact) > 1000


def test_failure_isolation_for_unknown_output_type(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    requested = ["summary", "not-a-real-type", "x"]
    job_id = add_job(engine, project_id, source_id, requested)

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 1
    types = {o["output_type"]: o["status"] for o in result["outputs"]}
    assert types["summary"] == "completed"
    assert types["x"] == "completed"
    assert types["not-a-real-type"] == "failed"
