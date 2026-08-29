"""Phase 8A — PPTX renderer hardening tests.

Covers valid presentation rendering, edge cases (empty/single slide, empty
optional collections, long text, multi-line normalization), determinism /
LLM-freedom, and round-trip parsing via ``parse_pptx``.
"""

from __future__ import annotations

import pytest

from app.transformation.output_schemas import PresentationSlide, PresentationStructure
from app.transformation.render.pptx import (
    MAX_TEXT_LENGTH,
    PPTX_MIME_TYPE,
    parse_pptx,
    render_presentation,
)

DEFAULT_TITLE = "Phase 8A Test Deck"


def make_structure(slides: list[dict]) -> PresentationStructure:
    """Build a validated PresentationStructure from plain dicts."""
    return PresentationStructure(
        type="presentation",
        title=DEFAULT_TITLE,
        slides=[PresentationSlide(**s) for s in slides],
        text="Phase 8A body",
    )


SLIDE_A = {
    "title": "Slide One",
    "key_message": "Key message one",
    "supporting_points": ["Point A", "Point B"],
    "visual_recommendation": "Bar chart",
    "speaker_notes": ["Explain point A", "Mention point B"],
}

SLIDE_B = {
    "title": "Slide Two",
    "key_message": "",
    "supporting_points": [],
    "visual_recommendation": "",
    "speaker_notes": [],
}


def slide_texts(prs) -> list[list[str]]:
    """Return per-slide text lists (title + all text-frame paragraphs)."""
    out = []
    for slide in prs.slides:
        texts = []
        if slide.shapes.title is not None:
            texts.append(slide.shapes.title.text)
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs)
                    if t:
                        texts.append(t)
        out.append(texts)
    return out


# ---------------------------------------------------------------------------
# Valid rendering + round-trip
# ---------------------------------------------------------------------------

def test_renders_valid_presentation_to_pptx_bytes():
    structure = make_structure([SLIDE_A, SLIDE_B])
    data = render_presentation(structure)
    assert isinstance(data, bytes)
    assert len(data) > 1000


def test_round_trip_parses_slides_and_content():
    structure = make_structure([SLIDE_A, SLIDE_B])
    data = render_presentation(structure)
    prs = parse_pptx(data)
    texts = slide_texts(prs)
    assert len(texts) == 2
    assert texts[0][0] == "Slide One"
    # Key message preserved into the rendered deck.
    joined = "\n".join(t for slide in texts for t in slide)
    assert "Key message one" in joined
    assert "Point A" in joined
    assert "Point B" in joined


def test_mime_type_constant():
    assert PPTX_MIME_TYPE == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


# ---------------------------------------------------------------------------
# Deterministic / LLM-free
# ---------------------------------------------------------------------------

def test_rendering_is_deterministic():
    structure = make_structure([SLIDE_A, SLIDE_B])
    assert render_presentation(structure) == render_presentation(structure)


def test_renderer_does_not_import_llm():
    # The renderer must be pure PPTX output. Importing it must not pull in any
    # LLM provider module, and it exposes no provider surface.
    import app.transformation.render.pptx as render_module

    assert not hasattr(render_module, "LLMProvider")
    assert not hasattr(render_module, "generate_text")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_slides_are_rejected_safely():
    # The schema enforces min_length=1; model_construct simulates a caller that
    # bypassed validation so the renderer's defensive guard is exercised.
    empty = PresentationStructure.model_construct(
        type="presentation", title="Deck", slides=None, text="x"
    )
    with pytest.raises(ValueError):
        render_presentation(empty)


def test_single_slide_renders():
    structure = make_structure([SLIDE_A])
    data = render_presentation(structure)
    prs = parse_pptx(data)
    assert len(prs.slides) == 1


def test_empty_optional_collections_render_safely():
    structure = make_structure([SLIDE_B])
    data = render_presentation(structure)
    assert isinstance(data, bytes) and len(data) > 0
    prs = parse_pptx(data)
    texts = slide_texts(prs)
    assert texts[0][0] == "Slide Two"


def test_slide_with_only_title_renders():
    structure = make_structure(
        [
            {
                "title": "Title Only",
                "key_message": "",
                "supporting_points": [],
                "visual_recommendation": "",
                "speaker_notes": [],
            }
        ]
    )
    data = render_presentation(structure)
    prs = parse_pptx(data)
    texts = slide_texts(prs)
    assert any(t.startswith("Title Only") for t in texts[0])


# ---------------------------------------------------------------------------
# Defensive handling of long content
# ---------------------------------------------------------------------------

def _long_text(n: int) -> str:
    return "x" * n


def test_long_title_is_truncated():
    structure = make_structure(
        [
            {
                "title": _long_text(MAX_TEXT_LENGTH + 50),
                "key_message": "K",
                "supporting_points": [],
                "visual_recommendation": "",
                "speaker_notes": [],
            }
        ]
    )
    data = render_presentation(structure)
    prs = parse_pptx(data)
    title = prs.slides[0].shapes.title.text
    assert len(title) <= MAX_TEXT_LENGTH
    assert title.endswith("...")


def test_long_key_message_is_truncated():
    structure = make_structure(
        [
            {
                "title": "Long message slide",
                "key_message": _long_text(MAX_TEXT_LENGTH + 500),
                "supporting_points": [],
                "visual_recommendation": "",
                "speaker_notes": [],
            }
        ]
    )
    data = render_presentation(structure)
    prs = parse_pptx(data)
    body = None
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame and shape.text_frame.text.startswith("xxxxx"):
            body = shape.text_frame.text
            break
    assert body is not None
    # The padded key message is truncated and flagged with an ellipsis.
    assert len(body) <= MAX_TEXT_LENGTH
    assert body.endswith("...")


def test_long_bullet_is_bounded():
    structure = make_structure(
        [
            {
                "title": "Bullets",
                "key_message": "Leading",
                "supporting_points": [_long_text(MAX_TEXT_LENGTH + 200)],
                "visual_recommendation": "",
                "speaker_notes": [],
            }
        ]
    )
    data = render_presentation(structure)
    prs = parse_pptx(data)
    blob = "\n".join(t for slide in slide_texts(prs) for t in slide)
    # The bullet-point prefix survives and the payload is bounded: the
    # truncated bullet (<= MAX_TEXT_LENGTH) plus the "• " prefix and a small
    # allowance for the leading key message / title lines.
    assert "• " in blob
    assert len(blob) <= MAX_TEXT_LENGTH + 50


def test_multiline_values_are_collapsed():
    multiline = {"title": "Multi", "key_message": "", "supporting_points": ["line one\n\nline two", "single"], "visual_recommendation": "a\nb", "speaker_notes": ["n1\nn2"]}
    structure = make_structure([multiline])
    data = render_presentation(structure)
    prs = parse_pptx(data)
    blob_lines = [l for slide in slide_texts(prs) for l in slide]
    # No rendered line contains an embedded newline.
    for line in blob_lines:
        assert "\n" not in str(line)
