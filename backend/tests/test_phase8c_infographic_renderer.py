"""Phase 8C — Infographic renderer tests.

Covers valid PDF/PNG rendering of an ``Infographic``, round-trip extraction,
MIME constants, determinism / LLM-freedom, empty optional fields, minimal
input, long-content truncation, multiline normalization, multi-page pagination
without content loss, page-bound confinement, PNG generation (single- and
multi-page), end-to-end infographic artifact persistence (PNG-primary + PDF
sibling), and a presentation/PPTX artifact regression.
"""

from __future__ import annotations

import math
import struct
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
from app.transformation.output_schemas import Infographic, InfographicSection
from app.transformation.render._documents import MAX_TEXT_LENGTH
from app.transformation.render.infographic import (
    INF_PNG_MIME_TYPE,
    PDF_MIME_TYPE,
    PNG_DPI,
    parse_infographic_pdf,
    render_infographic_pdf,
    render_infographic_png,
)
from app.transformation.render.pdf import PDF_MIME_TYPE as PDF_MIME_TYPE_CANONICAL
from app.transformation.render.pptx import PPTX_MIME_TYPE, parse_pptx
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def make_infographic(**overrides) -> Infographic:
    """Build a validated Infographic from plain overrides."""
    base = {
        "type": "infographic",
        "title": "Test Infographic",
        "key_messages": ["Key message one", "Key message two"],
        "sections": [
            {
                "heading": "Section One",
                "message": "Section one message.",
                "visual_suggestion": "Icon or chart",
            },
            {
                "heading": "Section Two",
                "message": "Section two message.",
                "visual_suggestion": "",
            },
        ],
        "layout_recommendation": "Vertical single-page layout",
        "visual_suggestions": ["Use a bold accent colour", "Keep text brief"],
        "text": "# Test Infographic\n\nA test infographic package.",
    }
    base.update(overrides)
    if "sections" in overrides:
        base["sections"] = [
            InfographicSection(**s) if isinstance(s, dict) else s
            for s in overrides["sections"]
        ]
    return Infographic(**base)


def pdf_text(byte_data: bytes) -> str:
    """Return all extractable text from rendered PDF bytes."""
    doc = parse_infographic_pdf(byte_data)
    return "".join(page.get_text("text") for page in doc)


def png_dimensions(byte_data: bytes) -> tuple[int, int]:
    """Return (width, height) of a PNG by parsing its IHDR chunk."""
    assert byte_data[:8] == PNG_MAGIC
    width = struct.unpack(">I", byte_data[16:20])[0]
    height = struct.unpack(">I", byte_data[20:24])[0]
    return width, height


def pdf_semantics(byte_data: bytes) -> tuple[int, str]:
    """Return (page_count, extracted_text) — the deterministic semantic view.

    PyMuPDF embeds a non-deterministic creation timestamp in the raw PDF bytes,
    so byte-identity is not guaranteed; the rendered text and page layout are.
    """
    doc = parse_infographic_pdf(byte_data)
    return doc.page_count, pdf_text(byte_data)


def make_db(with_canonical: bool = True):
    """In-memory sqlite seeded with a ready project/source/canonical."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email=f"p8c-{uuid.uuid4().hex}@example.test", name="P8C", role="operator")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Phase 8C")
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

def test_renders_valid_infographic_to_pdf_bytes():
    data = render_infographic_pdf(make_infographic())
    assert isinstance(data, bytes)
    assert len(data) > 100


def test_renders_valid_infographic_to_png_bytes_with_magic_header():
    data = render_infographic_png(make_infographic())
    assert isinstance(data, bytes)
    assert data[:8] == PNG_MAGIC
    assert len(data) > 100


def test_pdf_round_trip_preserves_content():
    infographic = make_infographic()
    doc = parse_infographic_pdf(render_infographic_pdf(infographic))
    assert doc.page_count >= 1
    text = pdf_text(render_infographic_pdf(infographic))
    assert infographic.title in text
    for message in infographic.key_messages:
        assert message in text
    for section in infographic.sections:
        assert section.heading in text
        assert section.message in text
    assert infographic.layout_recommendation in text


def test_single_page_png_dimensions_are_expected():
    width, height = png_dimensions(render_infographic_png(make_infographic()))
    # A4 at the fixed PNG_DPI (595/72*dpi and 842/72*dpi, rounded up).
    assert width == math.ceil(595 * PNG_DPI / 72)
    assert height == math.ceil(842 * PNG_DPI / 72)


def test_mime_type_constants():
    assert INF_PNG_MIME_TYPE == "image/png"
    assert PDF_MIME_TYPE == "application/pdf"
    # The infographic PDF uses the exact same canonical constant as the 8B PDF.
    assert PDF_MIME_TYPE == PDF_MIME_TYPE_CANONICAL


# ---------------------------------------------------------------------------
# Deterministic / LLM-free
# ---------------------------------------------------------------------------

def test_pdf_rendering_is_deterministic():
    infographic = make_infographic()
    assert pdf_semantics(render_infographic_pdf(infographic)) == pdf_semantics(
        render_infographic_pdf(infographic)
    )


def test_png_rendering_is_byte_deterministic():
    infographic = make_infographic()
    assert render_infographic_png(infographic) == render_infographic_png(infographic)


def test_renderer_does_not_import_llm():
    import app.transformation.render.infographic as render_module

    assert not hasattr(render_module, "LLMProvider")
    assert not hasattr(render_module, "generate_text")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_optional_fields_render_safely():
    infographic = make_infographic(
        visual_suggestions=[],
        sections=[
            {"heading": "Section One", "message": "Section one message.", "visual_suggestion": ""},
        ],
    )
    text = pdf_text(render_infographic_pdf(infographic))
    assert infographic.title in text
    assert "Section one message." in text
    # No orphan visual markers for the empty optional suggestion.
    assert "[Visual:]" not in text


def test_populated_visual_suggestion_and_suggestions_render():
    infographic = make_infographic(
        sections=[
            {
                "heading": "Section One",
                "message": "Section one message.",
                "visual_suggestion": "Bar chart",
            },
        ],
    )
    text = pdf_text(render_infographic_pdf(infographic))
    assert "[Visual: Bar chart]" in text
    assert "Use a bold accent colour" in text


def test_minimal_infographic_renders():
    infographic = Infographic(
        type="infographic",
        title="Minimal",
        key_messages=["Only message"],
        sections=[InfographicSection(heading="Only section", message="Only message body")],
        layout_recommendation="Simple card",
        text="x",
    )
    data = render_infographic_pdf(infographic)
    doc = parse_infographic_pdf(data)
    assert doc.page_count >= 1
    text = pdf_text(data)
    assert "Minimal" in text
    assert "Only message" in text
    assert "Only section" in text
    assert "Simple card" in text


def test_empty_required_fields_are_rejected_safely():
    # The schema enforces min_length=1; model_construct simulates a caller that
    # bypassed validation so the renderer's defensive guard is exercised.
    empty = Infographic.model_construct(
        type="infographic", title="X", key_messages=None, sections=None, layout_recommendation="x", text="x"
    )
    with pytest.raises(ValueError):
        render_infographic_pdf(empty)
    with pytest.raises(ValueError):
        render_infographic_png(empty)


# ---------------------------------------------------------------------------
# Defensive handling of long content
# ---------------------------------------------------------------------------

def _long_text(n: int) -> str:
    return "x" * n


def test_long_title_is_truncated_in_pdf():
    infographic = make_infographic(title=_long_text(MAX_TEXT_LENGTH + 50))
    text = pdf_text(render_infographic_pdf(infographic))
    assert "xxxxx" in text
    assert "..." in text
    assert len(text) < MAX_TEXT_LENGTH + 500


def test_long_key_message_is_bounded():
    infographic = make_infographic(key_messages=[_long_text(MAX_TEXT_LENGTH + 500)])
    text = pdf_text(render_infographic_pdf(infographic))
    assert "xxxxx" in text
    assert "..." in text
    assert len(text) < MAX_TEXT_LENGTH + 1000


def test_long_section_message_is_bounded():
    infographic = make_infographic(
        sections=[
            {"heading": "Big", "message": _long_text(MAX_TEXT_LENGTH + 300), "visual_suggestion": ""},
        ]
    )
    text = pdf_text(render_infographic_pdf(infographic))
    assert len(text) < MAX_TEXT_LENGTH + 1000


def test_multiline_values_are_collapsed_in_pdf():
    infographic = make_infographic(
        title="Multi",
        key_messages=["key line one\n\nkey line two"],
        sections=[
            {"heading": "H\na", "message": "bullet one\nbullet two", "visual_suggestion": "v one\nv two"},
        ],
        layout_recommendation="layout one\nlayout two",
    )
    text = pdf_text(render_infographic_pdf(infographic))
    # Normalizer collapses multi-line strings onto a single rendered line.
    assert "bullet one\nbullet two" not in text
    assert "bullet one bullet two" in text


def test_multi_page_infographic_paginates_without_losing_content():
    infographic = make_infographic(
        sections=[
            {
                "heading": f"Section {i}",
                "message": f"Section {i} message body.",
                "visual_suggestion": "",
            }
            for i in range(1, 150)
        ],
    )
    data = render_infographic_pdf(infographic)
    doc = parse_infographic_pdf(data)
    assert doc.page_count > 1
    text = pdf_text(data)
    assert "Section 1 message body." in text
    assert "Section 149 message body." in text
    assert infographic.layout_recommendation in text


def test_multi_page_png_is_a_valid_tall_image():
    infographic = make_infographic(
        sections=[
            {
                "heading": f"Section {i}",
                "message": f"Section {i} message body.",
                "visual_suggestion": "",
            }
            for i in range(1, 120)
        ],
    )
    assert parse_infographic_pdf(render_infographic_pdf(infographic)).page_count > 1

    data = render_infographic_png(infographic)
    assert data[:8] == PNG_MAGIC
    width, height = png_dimensions(data)
    single_width, single_height = png_dimensions(render_infographic_png(make_infographic()))
    # The composite keeps the page width and stacks pages vertically.
    assert width == single_width
    assert height > single_height


def test_pages_stay_within_printable_bounds():
    infographic = make_infographic(
        sections=[
            {
                "heading": f"Section {i}",
                "message": f"Section {i} message body.",
                "visual_suggestion": "Icon",
            }
            for i in range(1, 80)
        ],
    )
    doc = parse_infographic_pdf(render_infographic_pdf(infographic))
    for page in doc:
        page_rect = page.rect
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span["bbox"]
                    assert bbox[0] >= 0 and bbox[2] <= page_rect.width
                    assert bbox[1] >= 0 and bbox[3] <= page_rect.height


# ---------------------------------------------------------------------------
# End-to-end artifact persistence + presentation regression
# ---------------------------------------------------------------------------

def test_e2e_infographic_artifact_persisted_with_presentation_regression(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id, _ = add_job(engine, project_id, source_id, ["infographic", "presentation"])

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] == 2
    assert result["outputs_failed"] == 0

    with Session(engine, expire_on_commit=False) as db:
        outputs = db.execute(select(Output)).scalars().all()
        by_type = {o.output_type: o for o in outputs}

        # --- Infographic: PNG-primary + PDF sibling ---
        info = by_type["infographic"]
        assert info.status == "completed"
        assert info.mime_type == INF_PNG_MIME_TYPE
        assert info.storage_key
        expected_png_key = output_storage_key(project_id, job_id, info.id, INF_PNG_MIME_TYPE)
        assert info.storage_key == expected_png_key
        png_bytes = storage.read(info.storage_key)
        assert png_bytes[:8] == PNG_MAGIC
        assert info.output_metadata["artifact"] == "infographic"
        assert info.output_metadata["pdf_storage_key"].endswith(".pdf")
        pdf_bytes = storage.read(info.output_metadata["pdf_storage_key"])
        assert isinstance(pdf_bytes, bytes)
        assert parse_infographic_pdf(pdf_bytes).page_count >= 1
        assert "Test Source" in pdf_text(pdf_bytes)

        # --- Presentation regression: PPTX artifact unchanged ---
        pres = by_type["presentation"]
        assert pres.status == "completed"
        assert pres.mime_type == PPTX_MIME_TYPE
        expected_pptx_key = output_storage_key(project_id, job_id, pres.id, PPTX_MIME_TYPE)
        assert pres.storage_key == expected_pptx_key
        prs = parse_pptx(storage.read(pres.storage_key))
        assert len(prs.slides) >= 1


def test_e2e_presentation_only_job_still_persists_pptx(tmp_path: Path):
    storage = LocalStorage(tmp_path / "storage")
    engine, project_id, source_id = make_db()
    job_id, _ = add_job(engine, project_id, source_id, ["presentation"])

    with Session(engine, expire_on_commit=False) as db:
        result = run_transformation_job(
            db, job_id, llm_provider=FakeLLMProvider(), storage=storage,
        )

    assert result["outputs_completed"] == 1
    with Session(engine, expire_on_commit=False) as db:
        pres = db.execute(select(Output)).scalars().one()
        assert pres.status == "completed"
        assert pres.mime_type == PPTX_MIME_TYPE
        assert pres.storage_key.endswith(".pptx")
        prs = parse_pptx(storage.read(pres.storage_key))
        assert len(prs.slides) >= 1