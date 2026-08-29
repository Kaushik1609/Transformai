"""Phase 8D — Video package renderer tests.

Covers valid PDF and SRT rendering of a ``VideoPackage``, round-trip
extraction, MIME constants, deterministic / LLM-free rendering, deterministic
subtitle timing, empty optional fields, minimal input, long-content
truncation, multiline normalization, pagination without content loss,
page-bound confinement, end-to-end video artifact persistence (PDF primary +
SRT sibling), and a multi-output regression over existing renderers.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

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
from app.transformation.artifacts import output_storage_key
from app.transformation.llm import FakeLLMProvider
from app.transformation.output_schemas import VideoPackage, VideoScene
from app.transformation.render._documents import MAX_TEXT_LENGTH
from app.transformation.render.pdf import PDF_MIME_TYPE as PDF_MIME_TYPE_CANONICAL
from app.transformation.render.pptx import PPTX_MIME_TYPE, parse_pptx
from app.transformation.render.video import (
    MIN_SUBTITLE_DURATION_MS,
    PDF_MIME_TYPE,
    SRT_MIME_TYPE,
    SUBTITLE_CHARS_PER_SECOND,
    parse_video_package_pdf,
    parse_video_package_srt,
    render_video_package_pdf,
    render_video_package_srt,
)
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def make_video_package(**overrides) -> VideoPackage:
    """Build a validated VideoPackage from plain overrides."""
    base = {
        "type": "video",
        "title": "Test Video Package",
        "script": "Open on the source summary.\nIntroduce the key findings.",
        "storyboard": [
            {
                "title": "Opening",
                "description": "Anchoring shot of the report cover.",
                "narration": "Welcome to this briefing.",
                "subtitle": "Welcome to this briefing.",
                "visual_recommendation": "B-roll of report graphics",
            },
            {
                "title": "Key Findings",
                "description": "Overlay of key statistics.",
                "narration": "These are the main findings.",
                "subtitle": "Main findings.",
                "visual_recommendation": "",
            },
        ],
        "narration_full": "Welcome to this briefing.\nThese are the main findings.",
        "subtitles_full": "Welcome to this briefing.\nMain findings.",
        "visual_recommendations": ["Use a bold accent colour", "Keep captions short"],
        "text": "# Test Video Package\n\nA test video package.",
    }
    base.update(overrides)
    if "storyboard" in overrides:
        base["storyboard"] = [
            VideoScene(**s) if isinstance(s, dict) else s
            for s in overrides["storyboard"]
        ]
    return VideoPackage(**base)


def pdf_text(byte_data: bytes) -> str:
    """Return all extractable text from rendered PDF bytes."""
    doc = parse_video_package_pdf(byte_data)
    return "".join(page.get_text("text") for page in doc)


def pdf_semantics(byte_data: bytes) -> tuple[int, str]:
    """Return (page_count, extracted_text) — the deterministic semantic view.

    PyMuPDF embeds a non-deterministic creation timestamp in the raw PDF bytes,
    so byte-identity is not guaranteed; the rendered text and page layout are.
    """
    doc = parse_video_package_pdf(byte_data)
    return doc.page_count, pdf_text(byte_data)


def make_db(with_canonical: bool = True):
    """In-memory sqlite seeded with a ready project/source/canonical."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"p8d-{uuid.uuid4().hex}@example.test", name="P8D", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 8D")
        source = Source(
            id=uuid.uuid4(), project_id=project.id, source_type="text", status="ready",
            extracted_text="Source line one.\nSource line two.",
        )
        db.add_all([user, project, source])
        db.flush()
        if with_canonical:
            db.add(CanonicalContent(
                id=uuid.uuid4(), source_id=source.id, project_id=project.id, status="completed",
                title="Test Source", summary="A test source summary.",
                key_points=[{"text": "First key point", "source_chunk_ids": []}],
                recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            ))
        db.commit()
    return engine, project.id, source.id


def add_job(engine, project_id: uuid.UUID, source_id: uuid.UUID, output_types: list[str]) -> tuple[uuid.UUID, uuid.UUID]:
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
        return job.id, cfg.id


# ---------------------------------------------------------------------------
# Valid rendering + round-trip
# ---------------------------------------------------------------------------

def test_renders_valid_video_package_to_pdf_bytes():
    data = render_video_package_pdf(make_video_package())
    assert isinstance(data, bytes)
    assert len(data) > 100


def test_renders_valid_video_package_to_srt_bytes():
    data = render_video_package_srt(make_video_package())
    assert isinstance(data, bytes)
    assert data.startswith(b"1\n00:00:00,000 --> ")


def test_pdf_round_trip_preserves_content():
    package = make_video_package()
    doc = parse_video_package_pdf(render_video_package_pdf(package))
    assert doc.page_count >= 1
    text = pdf_text(render_video_package_pdf(package))
    assert package.title in text
    assert "Open on the source summary. Introduce the key findings." in text
    for scene in package.storyboard:
        assert scene.title in text
        assert scene.description in text
        assert scene.narration in text
        assert scene.subtitle in text
    assert "Welcome to this briefing. These are the main findings." in text
    assert "Use a bold accent colour" in text
    assert "Keep captions short" in text


def test_scene_blocks_are_numbered_in_order():
    package = make_video_package()
    text = pdf_text(render_video_package_pdf(package))
    assert "Scene 1 - Opening" in text
    assert "Scene 2 - Key Findings" in text
    assert text.index("Scene 1 - Opening") < text.index("Scene 2 - Key Findings")


def test_mime_type_constants():
    assert PDF_MIME_TYPE == "application/pdf"
    assert SRT_MIME_TYPE == "application/x-subrip"
    # The video package PDF uses the exact same canonical constant as the 8B PDF.
    assert PDF_MIME_TYPE == PDF_MIME_TYPE_CANONICAL


# ---------------------------------------------------------------------------
# Deterministic / LLM-free
# ---------------------------------------------------------------------------

def test_pdf_rendering_is_semantically_deterministic():
    package = make_video_package()
    assert pdf_semantics(render_video_package_pdf(package)) == pdf_semantics(
        render_video_package_pdf(package)
    )


def test_srt_rendering_is_byte_deterministic():
    package = make_video_package()
    assert render_video_package_srt(package) == render_video_package_srt(package)


def test_renderer_does_not_import_llm():
    import app.transformation.render.video as render_module

    assert not hasattr(render_module, "LLMProvider")
    assert not hasattr(render_module, "generate_text")


# ---------------------------------------------------------------------------
# SRT structure and deterministic timing
# ---------------------------------------------------------------------------

def test_srt_has_exactly_one_cue_per_scene():
    package = make_video_package()
    cues = parse_video_package_srt(render_video_package_srt(package))
    assert len(cues) == len(package.storyboard)


def test_srt_preserves_scene_order_and_subtitles():
    package = make_video_package(
        storyboard=[
            {"title": "Alpha", "description": "D1", "narration": "N1", "subtitle": "Sub alpha", "visual_recommendation": ""},
            {"title": "Beta", "description": "D2", "narration": "N2", "subtitle": "Sub beta", "visual_recommendation": ""},
        ]
    )
    cues = parse_video_package_srt(render_video_package_srt(package))
    assert [c[2] for c in cues] == ["Sub alpha", "Sub beta"]


def test_srt_timestamps_are_strictly_chronological_and_positive():
    package = make_video_package(
        storyboard=[
            {"title": f"Scene {i}", "description": "D", "narration": "N",
             "subtitle": f"subtitle number {i} text", "visual_recommendation": ""}
            for i in range(1, 6)
        ]
    )
    cues = parse_video_package_srt(render_video_package_srt(package))
    assert cues[0][0] == 0  # first cue starts at 00:00:00,000
    for (start, end, _), (next_start, _, _) in zip(cues, cues[1:]):
        assert end > start          # positive duration
        assert next_start == end    # strictly chronological, no gaps/overlap


def test_srt_duration_derived_from_subtitle_length():
    package = make_video_package(
        storyboard=[
            {"title": "Alpha", "description": "D", "narration": "N",
             "subtitle": "A fairly long subtitle line.", "visual_recommendation": ""},
            {"title": "Beta", "description": "D", "narration": "N",
             "subtitle": "cap", "visual_recommendation": "B-roll"},
        ]
    )
    cues = parse_video_package_srt(render_video_package_srt(package))
    assert len(cues) == 2
    for start, end, text in cues:
        expected = max(
            MIN_SUBTITLE_DURATION_MS,
            math.ceil((len(text) / SUBTITLE_CHARS_PER_SECOND) * 1000),
        )
        assert end - start == expected
        assert end - start >= MIN_SUBTITLE_DURATION_MS
    # The longer first scene spans longer than the floored minimum cue.
    assert cues[0][2] == "A fairly long subtitle line."
    assert cues[0][1] - cues[0][0] > MIN_SUBTITLE_DURATION_MS


def test_srt_round_trip_parse():
    package = make_video_package()
    raw = render_video_package_srt(package)
    cues = parse_video_package_srt(raw)
    assert cues[0][0] == 0
    # Each rendered cue body is the normalized scene subtitle, in scene order.
    expected = [s.subtitle for s in package.storyboard]
    assert [text for _, _, text in cues] == expected
    # The renderer always closes the file with a trailing blank line.
    assert render_video_package_srt(package).decode("utf-8").endswith("\n")


def test_srt_cues_never_contain_embedded_newlines():
    package = make_video_package(
        storyboard=[
            {"title": "T", "description": "D", "narration": "N",
             "subtitle": "cap line one\ncap line two", "visual_recommendation": ""},
        ]
    )
    raw = render_video_package_srt(package).decode("utf-8")
    blocks = [b for b in raw.strip().split("\n\n") if b.strip()]
    assert len(blocks) == 1
    # One cue = number + timing line + a single normalized body line.
    body_lines = blocks[0].splitlines()
    assert len(body_lines) == 3
    assert body_lines[2] == "cap line one cap line two"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_optional_fields_render_safely():
    package = make_video_package(
        visual_recommendations=[],
        storyboard=[
            {"title": "Solo", "description": "Described.", "narration": "Narrated.",
             "subtitle": "Captioned.", "visual_recommendation": ""},
        ],
    )
    text = pdf_text(render_video_package_pdf(package))
    assert "Solo" in text
    assert "Captioned." in text
    # No orphan visual markers for the empty optional fields.
    assert "Visual recommendation:" not in text
    assert "[Visual:]" not in text


def test_populated_visual_fields_render():
    package = make_video_package()
    text = pdf_text(render_video_package_pdf(package))
    assert "Visual recommendation:" in text
    assert "B-roll of report graphics" in text
    assert "VISUAL RECOMMENDATIONS" in text
    assert "Use a bold accent colour" in text


def test_minimal_video_package_renders():
    package = VideoPackage(
        type="video",
        title="Minimal",
        script="Say something.",
        storyboard=[VideoScene(title="One", description="A description.", narration="Narrate.", subtitle="Caption.")],
        narration_full="Full narration.",
        subtitles_full="Full subtitles.",
        text="x",
    )
    data = render_video_package_pdf(package)
    doc = parse_video_package_pdf(data)
    assert doc.page_count >= 1
    text = pdf_text(data)
    assert "Minimal" in text
    assert "Say something." in text
    assert "Scene 1 - One" in text
    assert "A description." in text
    assert "Full narration." in text
    assert "Full subtitles." in text


def test_empty_required_fields_are_rejected_safely():
    # The schema enforces min_length=1; model_construct simulates a caller that
    # bypassed validation so the renderer's defensive guard is exercised.
    missing_storyboard = VideoPackage.model_construct(
        type="video", title="X", script="y", storyboard=None,
        narration_full="n", subtitles_full="s", text="t",
    )
    empty_storyboard = VideoPackage.model_construct(
        type="video", title="X", script="y", storyboard=[],
        narration_full="n", subtitles_full="s", text="t",
    )
    for malformed in (missing_storyboard, empty_storyboard):
        with pytest.raises(ValueError):
            render_video_package_pdf(malformed)
        with pytest.raises(ValueError):
            render_video_package_srt(malformed)


# ---------------------------------------------------------------------------
# Defensive handling of long content
# ---------------------------------------------------------------------------

def _long_text(n: int) -> str:
    return "x" * n


def test_long_title_is_truncated_in_pdf():
    package = make_video_package(title=_long_text(MAX_TEXT_LENGTH + 50))
    text = pdf_text(render_video_package_pdf(package))
    assert "..." in text
    # No rendered field ever exceeds the defensive truncation cap.
    assert _long_text(MAX_TEXT_LENGTH + 1) not in text
    # The whole extracted document stays bounded even for a pathological title.
    assert len(text) < MAX_TEXT_LENGTH + 1000


def test_long_script_is_bounded():
    package = make_video_package(script=_long_text(MAX_TEXT_LENGTH + 500))
    text = pdf_text(render_video_package_pdf(package))
    assert "xxx" in text
    assert "..." in text
    assert len(text) < MAX_TEXT_LENGTH + 1000


def test_long_scene_subtitle_is_bounded_in_srt():
    package = make_video_package(
        storyboard=[{"title": "T", "description": "D", "narration": "N",
                     "subtitle": _long_text(MAX_TEXT_LENGTH + 300), "visual_recommendation": ""}],
    )
    raw = render_video_package_srt(package).decode("utf-8")
    assert "..." in raw
    assert len(raw) < MAX_TEXT_LENGTH + 1000


def test_multiline_values_are_collapsed_in_pdf():
    package = make_video_package(
        script="Part one\nPart two",
        narration_full="Narr one\nNarr two",
        subtitles_full="Sub one\nSub two",
        storyboard=[
            {"title": "Scene One", "description": "desc line one\ndesc line two",
             "narration": "say one\nsay two", "subtitle": "cap one\ncap two",
             "visual_recommendation": "v one\nv two"},
        ],
    )
    text = pdf_text(render_video_package_pdf(package))
    assert "Part one Part two" in text
    assert "Narr one Narr two" in text
    assert "Sub one Sub two" in text
    assert "desc line one desc line two" in text
    assert "say one say two" in text
    assert "cap one cap two" in text
    assert "v one v two" in text


def test_many_scenes_paginate_without_losing_content():
    package = make_video_package(
        storyboard=[
            {"title": f"Scene {i}", "description": f"Scene {i} description.",
             "narration": f"Narrate scene {i}.", "subtitle": f"Scene {i} caption.",
             "visual_recommendation": ""}
            for i in range(1, 121)
        ],
    )
    data = render_video_package_pdf(package)
    doc = parse_video_package_pdf(data)
    assert doc.page_count > 1
    text = pdf_text(data)
    assert "Scene 1 caption." in text
    assert "Scene 120 caption." in text
    # Yields a valid, fully ordered SRT too (no content dropped).
    cues = parse_video_package_srt(render_video_package_srt(package))
    assert len(cues) == 120


def test_pages_stay_within_printable_bounds():
    package = make_video_package(
        storyboard=[
            {"title": f"Scene {i}", "description": f"Scene {i} description.",
             "narration": f"Narrate scene {i}.", "subtitle": f"Scene {i} caption.",
             "visual_recommendation": "B-roll"}
            for i in range(1, 80)
        ],
    )
    doc = parse_video_package_pdf(render_video_package_pdf(package))
    for page in doc:
        page_rect = page.rect
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span["bbox"]
                    assert bbox[0] >= 0 and bbox[2] <= page_rect.width
                    assert bbox[1] >= 0 and bbox[3] <= page_rect.height


# ---------------------------------------------------------------------------
# End-to-end artifact persistence + existing renderer regression
# ---------------------------------------------------------------------------

def test_e2e_video_artifact_persisted(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id, _ = add_job(engine, project_id, source_id, ["video"])

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] == 1
    assert result["outputs_failed"] == 0

    with Session(engine, expire_on_commit=False) as db:
        video = db.execute(select(Output)).scalars().one()
        assert video.status == "completed"
        assert video.mime_type == PDF_MIME_TYPE
        assert video.storage_key
        expected_pdf_key = output_storage_key(project_id, job_id, video.id, PDF_MIME_TYPE)
        assert video.storage_key == expected_pdf_key
        pdf_bytes = storage.read(video.storage_key)
        assert isinstance(pdf_bytes, bytes)
        assert parse_video_package_pdf(pdf_bytes).page_count >= 1
        assert "Test Source" in pdf_text(pdf_bytes)
        assert "Deterministic script" in pdf_text(pdf_bytes)

        assert video.output_metadata["artifact"] == "video"
        srt_key = video.output_metadata["subtitle_storage_key"]
        assert srt_key.endswith(".srt")
        expected_srt_key = output_storage_key(project_id, job_id, video.id, SRT_MIME_TYPE)
        assert srt_key == expected_srt_key
        srt_bytes = storage.read(srt_key)
        assert isinstance(srt_bytes, bytes)
        cues = parse_video_package_srt(srt_bytes)
        assert len(cues) >= 1
        assert cues[0][0] == 0


def test_e2e_multi_output_job_video_with_existing_renderers(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id, _ = add_job(engine, project_id, source_id, ["video", "presentation", "summary", "advisory"])

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] == 4
    assert result["outputs_failed"] == 0

    with Session(engine, expire_on_commit=False) as db:
        outputs = db.execute(select(Output)).scalars().all()
        by_type = {o.output_type: o for o in outputs}

        # --- Video: PDF-primary + SRT sibling, unchanged contract ---
        video = by_type["video"]
        assert video.status == "completed"
        assert video.mime_type == PDF_MIME_TYPE
        assert video.storage_key.endswith(".pdf")
        assert parse_video_package_pdf(storage.read(video.storage_key)).page_count >= 1
        assert video.output_metadata["subtitle_storage_key"].endswith(".srt")
        assert parse_video_package_srt(
            storage.read(video.output_metadata["subtitle_storage_key"])
        )

        # --- Presentation regression: PPTX artifact unchanged ---
        pres = by_type["presentation"]
        assert pres.status == "completed"
        assert pres.mime_type == PPTX_MIME_TYPE
        expected_pptx_key = output_storage_key(project_id, job_id, pres.id, PPTX_MIME_TYPE)
        assert pres.storage_key == expected_pptx_key
        prs = parse_pptx(storage.read(pres.storage_key))
        assert len(prs.slides) >= 1

        # --- Text outputs remain text-only (no spurious artifact) ---
        for output_type in ("summary", "advisory"):
            output = by_type[output_type]
            assert output.status == "completed"
            assert output.text_content.strip()
            assert output.storage_key is None