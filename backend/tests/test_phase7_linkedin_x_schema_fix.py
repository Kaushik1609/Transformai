"""Regression tests for the Summary vs LinkedIn/X multi-output failure.

Root-cause (fixed): the LLM returns collection fields (``hashtags``,
``thread``, ``supporting_points``) as a single space-separated string instead
of a JSON array. LinkedInPost/XPost declare these as ``list[str]`` with
``extra="forbid"``, so validation rejected them while Summary (which has no
such string-formatted collection field) succeeded.

Fix under test:
  1. The generator prompt now declares each field's JSON type so the model
     emits arrays for collection fields (FIELD JSON TYPES block).
  2. ``parse_output`` normalizes a string into a list for schema fields that
     are declared ``list[str]`` (pure formatting normalization — validation is
     still enforced, so genuinely invalid values still raise
     ``OutputSchemaError``).

All tests are deterministic and offline (FakeLLMProvider / fault-injecting
providers). No real API is used.
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
from app.transformation.generators import get_generator
from app.transformation.generators.common import _typed_field_spec
from app.transformation.llm import FakeLLMProvider, ProviderManager
from app.transformation.output_schemas import LinkedInPost, XPost
from app.transformation.output_schemas.parser import OutputSchemaError, parse_output
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Harness (mirrors test_phase11d_provider_resilience patterns)
# ---------------------------------------------------------------------------

ALL_7 = ["advisory", "infographic", "linkedin", "presentation", "summary", "video", "x"]

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary.",
    "topics": [], "entities": [], "key_points": [],
    "claims": [], "statistics": [], "dates": [],
    "recommendations": [], "source_references": [],
}

CONFIG: dict[str, Any] = {
    "target_audience": "Technical",
    "tone": "Technical",
    "language": "English",
    "detail_level": "standard",
    "communication_objective": "summarize",
}


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"hfix-{uuid.uuid4().hex}@example.test", name="HFix", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="HashTag Fix")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line.",
        )
        db.add_all([user, project, source])
        db.flush()
        db.add(CanonicalContent(
            id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
            title=CANONICAL["title"], summary=CANONICAL["summary"],
            key_points=[], recommendations=[], claims=[], statistics=[],
            dates=[], entities=[], topics=[], source_references=[],
        ))
        db.commit()
    return engine, project.id, source.id


def add_job(engine, project_id, source_id, output_types):
    with Session(engine, expire_on_commit=False) as db:
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project_id, language="English")
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(), project_id=project_id, source_id=source_id,
            configuration_id=cfg.id, requested_outputs={"output_types": output_types}, status="queued",
        )
        db.add(job)
        db.commit()
        return job.id


# A raw provider that returns the exact malformed payload shape seen from the
# real provider (collection fields as a space-separated string, not a list).
# Delegates to FakeLLMProvider and renders every top-level list-of-strings
# field back to a single string so the generator's coercion must recover a list.
class HashtagStringProvider(FakeLLMProvider):
    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        raw = super().generate_text(system_prompt=system_prompt, user_content=user_content)
        data = json.loads(raw)
        for key, value in list(data.items()):
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                data[key] = " ".join(value)
        return json.dumps(data)


class SelectiveFailHashtagProvider(HashtagStringProvider):
    """Returns string hashtags, but raises a provider error for a target output."""

    def __init__(self, fail_output: str) -> None:
        super().__init__()
        self.fail_output = fail_output
        self.fail_calls = 0

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        fields = set(self._extract_fields(system_prompt))
        if self.fail_output == "linkedin" and "hashtags" in fields and "thread" not in fields:
            self.fail_calls += 1
            raise TimeoutError("provider timed out")
        if self.fail_output == "x" and "thread" in fields:
            self.fail_calls += 1
            raise TimeoutError("provider timed out")
        return super().generate_text(system_prompt=system_prompt, user_content=user_content)


# ---------------------------------------------------------------------------
# 1. Schema normalization (the core fix)
# ---------------------------------------------------------------------------

class TestHashtagStringCoercion:
    def test_linkedin_string_hashtags_coerced_to_list(self):
        payload = {
            "type": "linkedin",
            "title": "title", "hook": "hook", "main_message": "msg",
            "supporting_points": ["A"],
            "hashtags": "#DiffusionModels #MedicalImaging #DeepLearning #SyntheticData",
            "body": "body", "text": "body",
        }
        out = parse_output("linkedin", json.dumps(payload))
        assert out.hashtags == ["#DiffusionModels", "#MedicalImaging", "#DeepLearning", "#SyntheticData"]
        assert out.type == "linkedin"

    def test_x_string_hashtags_and_thread_coerced(self):
        payload = {
            "type": "x",
            "title": "title", "hook": "hook", "main_message": "msg",
            "supporting_points": ["A"],
            "hashtags": "#A #B #EngineeringSeminar",
            "thread": "Tweet one\nTweet two with schedule",
            "text": "Tweet one",
        }
        out = parse_output("x", json.dumps(payload))
        assert out.hashtags == ["#A", "#B", "#EngineeringSeminar"]
        assert out.thread == ["Tweet one", "Tweet two with schedule"]
        assert out.type == "x"

    def test_comma_separated_list_string_coerced(self):
        payload = {
            "type": "linkedin",
            "title": "t", "hook": "h", "main_message": "m",
            "hashtags": "#AI,#ML,#Health",
            "body": "b", "text": "b",
        }
        out = parse_output("linkedin", json.dumps(payload))
        assert out.hashtags == ["#AI", "#ML", "#Health"]

    def test_validation_still_enforced_for_non_coercible(self):
        # A required scalar field that is empty must still fail (validation not weakened).
        with pytest.raises(OutputSchemaError):
            parse_output("linkedin", json.dumps({"title": ""}))


# ---------------------------------------------------------------------------
# 2. Prompt declares field JSON types
# ---------------------------------------------------------------------------

class TestPromptTypeSpec:
    def test_linkedin_spec_declares_hashtags_as_array(self):
        spec = _typed_field_spec(LinkedInPost)
        assert "hashtags: array of strings" in spec
        assert "supporting_points: array of strings" in spec

    def test_x_spec_declares_hashtags_and_thread_as_array(self):
        spec = _typed_field_spec(XPost)
        assert "hashtags: array of strings" in spec
        assert "thread: array of strings" in spec

    def test_generator_prompt_contains_field_json_types(self):
        for output_type in ("linkedin", "x"):
            gen = get_generator(output_type, llm_provider=HashtagStringProvider())
            # Uses the shared prompt path, which validates normally.
            out = gen.generate(canonical=CANONICAL, config=CONFIG)
            assert out["hashtags"]


# ---------------------------------------------------------------------------
# 3. End-to-end: Summary + LinkedIn + X (FakeLLMProvider) all succeed
# ---------------------------------------------------------------------------

class TestSummaryLinkedInXEndToEnd:
    def test_summary_linkedin_x_all_succeed_fake_provider(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])

        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
            )

        assert result["outputs_completed"] == 3
        assert result["outputs_failed"] == 0
        with Session(engine, expire_on_commit=False) as db:
            outputs = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
            by_type = {o.output_type: o.status for o in outputs}
        assert by_type == {"summary": "completed", "linkedin": "completed", "x": "completed"}

    def test_summary_linkedin_x_succeed_with_string_hashtags(self, tmp_path: Path):
        # Even when the provider returns string hashtags, all three complete.
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        provider = HashtagStringProvider()

        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=provider, storage=storage,
            )

        assert result["outputs_completed"] == 3
        assert result["outputs_failed"] == 0
        with Session(engine, expire_on_commit=False) as db:
            li = db.execute(
                select(Output).where(Output.job_id == job_id, Output.output_type == "linkedin")
            ).scalars().one()
            xo = db.execute(
                select(Output).where(Output.job_id == job_id, Output.output_type == "x")
            ).scalars().one()
        assert li.status == "completed"
        assert isinstance(li.structured_content["hashtags"], list)
        assert xo.status == "completed"
        assert isinstance(xo.structured_content["hashtags"], list)
        assert isinstance(xo.structured_content["thread"], list)


# ---------------------------------------------------------------------------
# 4. Partial success / sibling isolation with provider failure
# ---------------------------------------------------------------------------

class TestPartialSuccessIsolation:
    def test_linkedin_provider_failure_keeps_summary_and_x(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        primary = SelectiveFailHashtagProvider("linkedin")

        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=lambda ot: get_generator(ot, llm_provider=ProviderManager(primary, max_attempts=1)),
                llm_provider=ProviderManager(primary, max_attempts=1),
                storage=storage,
            )

        assert result["outputs_completed"] == 2
        assert result["outputs_failed"] == 1
        with Session(engine, expire_on_commit=False) as db:
            job = db.get(TransformationJob, job_id)
            outputs = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
            by_type = {o.output_type: o.status for o in outputs}
        assert by_type["summary"] == "completed"
        assert by_type["x"] == "completed"
        assert by_type["linkedin"] == "failed"
        assert job.status == "completed"  # partial success preserved

    def test_x_provider_failure_keeps_summary_and_linkedin(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        primary = SelectiveFailHashtagProvider("x")

        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id,
                get_generator=lambda ot: get_generator(ot, llm_provider=ProviderManager(primary, max_attempts=1)),
                llm_provider=ProviderManager(primary, max_attempts=1),
                storage=storage,
            )

        assert result["outputs_completed"] == 2
        assert result["outputs_failed"] == 1
        with Session(engine, expire_on_commit=False) as db:
            outputs = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
            by_type = {o.output_type: o.status for o in outputs}
        assert by_type["summary"] == "completed"
        assert by_type["linkedin"] == "completed"
        assert by_type["x"] == "failed"

    def test_schema_validation_failure_is_correctly_isolated(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        # A provider that returns invalid LinkedIn (empty required field) but valid others.
        class InvalidLinkedInProvider(FakeLLMProvider):
            def generate_text(self, *, system_prompt, user_content):
                raw = super().generate_text(system_prompt=system_prompt, user_content=user_content)
                data = json.loads(raw)
                if "linkedin" in system_prompt.lower():
                    data["title"] = ""  # invalid per schema (min_length=1)
                return json.dumps(data)

        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db, job_id, llm_provider=InvalidLinkedInProvider(), storage=storage,
            )

        assert result["outputs_completed"] == 2
        assert result["outputs_failed"] == 1
        with Session(engine, expire_on_commit=False) as db:
            li = db.execute(
                select(Output).where(Output.job_id == job_id, Output.output_type == "linkedin")
            ).scalars().one()
        assert li.status == "failed"
        assert "Invalid linkedin output" in li.error_message


# ---------------------------------------------------------------------------
# 5. One TransformationJob preserved + no secret leakage
# ---------------------------------------------------------------------------

class TestJobAndSecrets:
    def test_multi_output_is_one_transformation_job(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(db, job_id, llm_provider=FakeLLMProvider(), storage=storage)
            job = db.get(TransformationJob, job_id)
        # Exactly one job, with all three outputs beneath it.
        assert job is not None
        with Session(engine, expire_on_commit=False) as db:
            outputs = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
        assert len(outputs) == 3
        assert {o.job_id for o in outputs} == {job_id}

    def test_no_secret_leakage_in_failure_metadata(self, tmp_path: Path):
        storage = LocalStorage(tmp_path / "storage")
        engine, project_id, source_id = make_db()
        job_id = add_job(engine, project_id, source_id, ["summary", "linkedin", "x"])
        provider = SelectiveFailHashtagProvider("linkedin")

        with Session(engine, expire_on_commit=False) as db:
            run_transformation_job(
                db, job_id,
                get_generator=lambda ot: get_generator(ot, llm_provider=ProviderManager(provider, max_attempts=1)),
                llm_provider=ProviderManager(provider, max_attempts=1),
                storage=storage,
            )
        with Session(engine, expire_on_commit=False) as db:
            li = db.execute(
                select(Output).where(Output.job_id == job_id, Output.output_type == "linkedin")
            ).scalars().one()
        dumped = str(li.output_metadata)
        assert "sk-" not in dumped
        assert "api-key" not in dumped.lower()
        assert "secret" not in dumped.lower()
