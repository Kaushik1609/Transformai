"""Phase 8B — DOCX renderer hardening tests.

Covers valid Executive Summary / Advisory rendering, edge cases (empty optional
collections, long text, multi-line normalization), determinism / LLM-freedom,
and round-trip parsing via ``parse_docx``.
"""

from __future__ import annotations

import pytest

from app.transformation.output_schemas import Advisory, ExecutiveSummary
from app.transformation.render._documents import MAX_TEXT_LENGTH
from app.transformation.render.docx import (
    DOCX_MIME_TYPE,
    parse_docx,
    render_advisory_docx,
    render_executive_summary_docx,
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


def docx_paragraphs(doc):
    """Return section headings, titles and bullet text from a parsed docx."""
    title = [p.text for p in doc.paragraphs if p.style.name == "Title"]
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    body = [p.text for p in doc.paragraphs if p.style.name in ("List Bullet", "Normal")]
    return title, headings, body


def all_text(doc):
    return [p.text for p in doc.paragraphs]


# ---------------------------------------------------------------------------
# Valid rendering + round-trip
# ---------------------------------------------------------------------------

def test_renders_executive_summary_to_docx_bytes():
    data = render_executive_summary_docx(make_summary())
    assert isinstance(data, bytes)
    assert len(data) > 1000


def test_round_trip_summary_preserves_content():
    doc = parse_docx(render_executive_summary_docx(make_summary()))
    title, headings, _ = docx_paragraphs(doc)
    assert title == ["Test Executive Summary"]
    assert "Summary" in headings
    assert "Key Findings" in headings
    joined = "\n".join(all_text(doc))
    assert "Finding one" in joined
    assert "Finding two" in joined
    assert "Recommend one" in joined
    assert "Action one" in joined


def test_renders_advisory_to_docx_bytes():
    data = render_advisory_docx(make_advisory())
    assert isinstance(data, bytes)
    assert len(data) > 1000


def test_round_trip_advisory_preserves_content():
    doc = parse_docx(render_advisory_docx(make_advisory()))
    title, headings, _ = docx_paragraphs(doc)
    assert title == ["Test Advisory"]
    assert {
        "Situation",
        "Key Findings",
        "Impact and Risk",
        "Affected Parties",
        "Recommended Actions",
    } <= set(headings)
    joined = "\n".join(all_text(doc))
    assert "Act one" in joined
    assert "Party one" in joined


def test_mime_type_constant():
    assert DOCX_MIME_TYPE == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ---------------------------------------------------------------------------
# Deterministic / LLM-free
# ---------------------------------------------------------------------------

def test_summary_rendering_is_deterministic():
    summary = make_summary()
    assert render_executive_summary_docx(summary) == render_executive_summary_docx(summary)


def test_advisory_rendering_is_deterministic():
    advisory = make_advisory()
    assert render_advisory_docx(advisory) == render_advisory_docx(advisory)


def test_docx_renderer_does_not_import_llm():
    import app.transformation.render.docx as render_module

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
    doc = parse_docx(render_executive_summary_docx(summary))
    title, headings, _ = docx_paragraphs(doc)
    assert title == ["Test Executive Summary"]
    assert "Summary" in headings
    # Empty sections simply do not appear.
    assert "Key Findings" not in headings
    assert "Recommendations" not in headings


def test_single_required_field_document_renders():
    summary = make_summary(
        context="", key_findings=[], key_facts=[],
        recommendations=[], action_items=[],
    )
    data = render_executive_summary_docx(summary)
    doc = parse_docx(data)
    joined = "\n".join(all_text(doc))
    assert "A test summary paragraph." in joined


# ---------------------------------------------------------------------------
# Defensive handling of long content
# ---------------------------------------------------------------------------

def _long_text(n: int) -> str:
    return "x" * n


def test_long_title_is_truncated_in_docx():
    summary = make_summary(title=_long_text(MAX_TEXT_LENGTH + 50))
    doc = parse_docx(render_executive_summary_docx(summary))
    title, _, _ = docx_paragraphs(doc)
    assert title
    assert len(title[0]) <= MAX_TEXT_LENGTH
    assert title[0].endswith("...")


def test_long_finding_is_truncated_in_docx():
    summary = make_summary(key_findings=[_long_text(MAX_TEXT_LENGTH + 500)])
    doc = parse_docx(render_executive_summary_docx(summary))
    joined = "\n".join(all_text(doc))
    assert "xxxxx" in joined
    long_line = next(l for l in all_text(doc) if l.startswith("xxxxx"))
    assert len(long_line) <= MAX_TEXT_LENGTH
    assert long_line.endswith("...")


def test_multiline_values_are_collapsed_in_docx():
    summary = make_summary(
        title="Multi",
        summary="line one\n\nline two",
        key_findings=["bullet one\nbullet two", "single"],
    )
    doc = parse_docx(render_executive_summary_docx(summary))
    for line in all_text(doc):
        assert "\n" not in line


# ---------------------------------------------------------------------------
# Shared normalizer behaviour
# ---------------------------------------------------------------------------

def test_docx_and_pdf_share_section_normalizer():
    # Both renderers consume the same format-agnostic section normalizer, so
    # contentious content choices cannot diverge between formats.
    from app.transformation.render._documents import advisory_sections, executive_summary_sections

    exec_sections = executive_summary_sections(make_summary())
    adv_sections = advisory_sections(make_advisory())
    assert exec_sections[0][1][0] == "Test Executive Summary"
    assert adv_sections[0][1][0] == "Test Advisory"
    assert "Situation" in [h for h, _ in adv_sections]
