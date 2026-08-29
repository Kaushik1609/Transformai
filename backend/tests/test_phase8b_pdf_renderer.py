"""Phase 8B — PDF renderer hardening tests.

Covers valid Executive Summary / Advisory rendering, edge cases (empty optional
collections, long text, multi-line normalization, multi-page overflow),
determinism / LLM-freedom, and round-trip parsing via ``parse_pdf``.
"""

from __future__ import annotations

import pytest

from app.transformation.output_schemas import Advisory, ExecutiveSummary
from app.transformation.render._documents import MAX_TEXT_LENGTH
from app.transformation.render.pdf import (
    PAGE_HEIGHT,
    PDF_MIME_TYPE,
    parse_pdf,
    render_advisory_pdf,
    render_executive_summary_pdf,
)


def make_summary(**overrides) -> ExecutiveSummary:
    base = {
        "title": "Test Executive Summary",
        "summary": "A test summary paragraph.",
        "context": "Some context.",
        "key_findings": ["Finding one", "Finding two"],
        "key_facts": ["Fact one"],
        "recommendations": ["Recommend one"],
        "action_items": ["Action one"],
        "text": "# Test Executive Summary\n\nA test summary paragraph.",
    }
    base.update(overrides)
    return ExecutiveSummary(**base)


def make_advisory(**overrides) -> Advisory:
    base = {
        "title": "Test Advisory",
        "situation": "A test situation.",
        "key_findings": ["Finding A"],
        "impact_risk": ["Risk one"],
        "affected_parties": ["Party one"],
        "recommended_actions": ["Act one"],
        "text": "# Test Advisory\n\nA test situation.",
    }
    base.update(overrides)
    return Advisory(**base)


def pdf_text(byte_data: bytes) -> str:
    doc = parse_pdf(byte_data)
    return "".join(page.get_text("text") for page in doc)


# ---------------------------------------------------------------------------
# Valid rendering + round-trip
# ---------------------------------------------------------------------------

def test_renders_executive_summary_to_pdf_bytes():
    data = render_executive_summary_pdf(make_summary())
    assert isinstance(data, bytes)
    assert len(data) > 100


def test_round_trip_summary_preserves_content():
    data = render_executive_summary_pdf(make_summary())
    doc = parse_pdf(data)
    assert doc.page_count >= 1
    text = pdf_text(data)
    assert "Test Executive Summary" in text
    assert "Finding one" in text
    assert "Finding two" in text
    assert "Recommend one" in text


def test_renders_advisory_to_pdf_bytes():
    data = render_advisory_pdf(make_advisory())
    assert isinstance(data, bytes)
    assert len(data) > 100


def test_round_trip_advisory_preserves_content():
    data = render_advisory_pdf(make_advisory())
    doc = parse_pdf(data)
    assert doc.page_count >= 1
    text = pdf_text(data)
    assert "Test Advisory" in text
    assert "Situation" in text
    assert "Act one" in text
    assert "Party one" in text


def test_mime_type_constant():
    assert PDF_MIME_TYPE == "application/pdf"


# ---------------------------------------------------------------------------
# Deterministic / LLM-free
# ---------------------------------------------------------------------------

def pdf_semantics(byte_data: bytes) -> tuple[int, str]:
    """Return (page_count, extracted_text) — the deterministic semantic view.

    PyMuPDF embeds a non-deterministic creation timestamp in the raw PDF bytes,
    so byte-identity is not guaranteed; the rendered text and page layout are.
    These two values are the meaningful determinism contract.
    """
    doc = parse_pdf(byte_data)
    return doc.page_count, pdf_text(byte_data)


def test_summary_rendering_is_deterministic():
    summary = make_summary()
    assert pdf_semantics(render_executive_summary_pdf(summary)) == pdf_semantics(
        render_executive_summary_pdf(summary)
    )


def test_advisory_rendering_is_deterministic():
    advisory = make_advisory()
    assert pdf_semantics(render_advisory_pdf(advisory)) == pdf_semantics(
        render_advisory_pdf(advisory)
    )


def test_pdf_renderer_does_not_import_llm():
    import app.transformation.render.pdf as render_module

    assert not hasattr(render_module, "LLMProvider")
    assert not hasattr(render_module, "generate_text")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_optional_collections_render_safely():
    summary = make_summary(
        context="",
        key_findings=[],
        key_facts=[],
        recommendations=[],
        action_items=[],
    )
    data = render_executive_summary_pdf(summary)
    doc = parse_pdf(data)
    assert doc.page_count >= 1
    text = pdf_text(data)
    assert "Test Executive Summary" in text
    assert "A test summary paragraph." in text


def test_single_required_field_document_renders():
    advisory = make_advisory(
        key_findings=[], impact_risk=[], affected_parties=[], recommended_actions=[]
    )
    data = render_advisory_pdf(advisory)
    doc = parse_pdf(data)
    assert doc.page_count >= 1


# ---------------------------------------------------------------------------
# Defensive handling of long content / multi-page
# ---------------------------------------------------------------------------

def _long_text(n: int) -> str:
    return "x" * n


def test_long_title_is_truncated_in_pdf():
    summary = make_summary(title=_long_text(MAX_TEXT_LENGTH + 50))
    text = pdf_text(render_executive_summary_pdf(summary))
    assert "xxxxx" in text
    assert "..." in text
    # Overall page text is bounded: the truncated title (capped line) plus the
    # short summary content — never a runaway blob of the raw 2000+ char title.
    assert len(text) < MAX_TEXT_LENGTH + 500


def test_long_finding_is_truncated_in_pdf():
    summary = make_summary(key_findings=[_long_text(MAX_TEXT_LENGTH + 500)])
    text = pdf_text(render_executive_summary_pdf(summary))
    assert "xxxxx" in text
    assert "..." in text
    # Bounded: the finding is capped at MAX_TEXT_LENGTH before layout; the total
    # extracted page text cannot exceed the cap plus a small allowance.
    assert len(text) < MAX_TEXT_LENGTH + 1000


def test_multiline_values_are_collapsed_in_pdf():
    summary = make_summary(
        title="Multi",
        summary="line one\n\nline two",
        key_findings=["bullet one\nbullet two", "single"],
    )
    text = pdf_text(render_executive_summary_pdf(summary))
    # Normalizer collapses multi-line strings onto a single rendered line.
    assert "bullet one\nbullet two" not in text
    assert "bullet one bullet two" in text


def test_multi_page_document_paginates_without_losing_content():
    # Enough content to exceed a single A4 page; all of it must be extractable.
    summary = make_summary(
        key_findings=[f"Finding number {i}" for i in range(1, 400)],
        recommendations=[f"Recommendation number {i}" for i in range(1, 100)],
    )
    data = render_executive_summary_pdf(summary)
    doc = parse_pdf(data)
    assert doc.page_count > 1
    text = pdf_text(data)
    assert "Finding number 399" in text
    assert "Finding number 1" in text


def test_pages_stay_within_printable_bounds():
    # Every rendered block is confined inside the page margins (no overflow).
    summary = make_summary(key_findings=[f"Point {i}" for i in range(60)])
    doc = parse_pdf(render_executive_summary_pdf(summary))
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span["bbox"]
                    assert bbox[1] >= 0 and bbox[3] <= PAGE_HEIGHT
