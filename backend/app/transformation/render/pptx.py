"""Render a validated PresentationStructure into a real .pptx file.

Uses python-pptx to produce slides with titles, key-message content,
supporting points, speaker notes and (on the notes slide) a visual
recommendation line.  Returns the file bytes so the caller can persist them
through the storage abstraction.

Phase 8A hardening:
  * Rendering remains deterministic and LLM-free — it consumes the validated
    ``PresentationStructure`` Pydantic model directly and never invokes a
    language model.
  * Empty-slide input is rejected with a clear ``ValueError`` (the schema
    enforces ``min_length=1``; this is a defensive guard for callers that
    bypass schema validation).
  * Single-slide presentations render correctly.
  * Long titles / key messages / bullet text are truncated defensively so a
    single pathological string cannot produce exploded run-on output.
  * Multi-line list items are normalized to a single line per paragraph so
    slide layout stays deterministic.
  * Empty optional collections (``supporting_points``, ``speaker_notes``,
    ``visual_recommendation``) render safely.
  * ``parse_pptx()`` round-trip verification is preserved.
"""

from __future__ import annotations

from io import BytesIO

from pptx import Presentation

from app.transformation.output_schemas import PresentationStructure

PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

# Defensive cap on a single rendered line.  Generous enough that normal
# content is never touched, but bounds pathological long strings so a value
# cannot bloat a slide placeholder into a massive blob of text.
MAX_TEXT_LENGTH = 2000
# Hard cap on supporting points / speaker notes rendered per slide so a
# degenerate output cannot create an unbounded number of paragraphs.
MAX_BULLETS_PER_SLIDE = 200


def render_presentation(structure: PresentationStructure) -> bytes:
    """Render a presentation structure into PPTX bytes."""
    if not structure.slides:
        raise ValueError("Presentation requires at least one slide.")

    prs = Presentation()
    # Use the title+content layout (index 1) which exposes title + body.  When
    # the template exposes only a minimal layout set we fall back to layout 0
    # and suppress the in-body visual-recommendation line (no content body).
    has_content_layout = len(prs.slide_layouts) > 1
    layout = prs.slide_layouts[1] if has_content_layout else prs.slide_layouts[0]

    for slide in structure.slides:
        s = prs.slides.add_slide(layout)
        if s.shapes.title is not None:
            s.shapes.title.text = _truncate(_clean_line(slide.title))

        body_lines = _iter_body_lines(slide, include_visual=has_content_layout)

        # Write the (capped) body content into the idx==1 placeholder when one
        # is present.  A body placeholder is optional; when absent we simply
        # render an otherwise-empty slide, which python-pptx allows.
        body_placeholder = None
        for placeholder in s.placeholders:
            if placeholder.placeholder_format.idx == 1:
                body_placeholder = placeholder
                break
        if body_placeholder is not None and body_lines:
            tf = body_placeholder.text_frame
            tf.clear()
            for index, line in enumerate(body_lines):
                paragraph = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
                paragraph.text = line

        # Speaker notes (with visual recommendation appended) are rendered on
        # the notes slide whenever either is present.  A slide with no notes
        # simply has an empty notes frame.
        note_lines = _iter_notes(slide)
        if note_lines:
            notes_frame = s.notes_slide.notes_text_frame
            notes_frame.text = "\n".join(note_lines)

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _iter_body_lines(slide, *, include_visual: bool) -> list[str]:
    """Collect the deterministic, capped body lines for a slide.

    Handles empty optional collections and truncates/normalizes each line.
    ``include_visual`` mirrors the original behaviour of appending the
    ``[Visual: ...]`` line only when a real content body layout is available.
    """
    lines: list[str] = []

    if slide.key_message:
        lines.append(_truncate(_clean_line(slide.key_message)))

    for point in slide.supporting_points[:MAX_BULLETS_PER_SLIDE]:
        cleaned = _clean_line(point)
        if cleaned:
            lines.append(f"• {_truncate(cleaned)}")

    if include_visual and slide.visual_recommendation:
        lines.append(
            f"[Visual: {_truncate(_clean_line(slide.visual_recommendation))}]"
        )

    return lines


def _iter_notes(slide) -> list[str]:
    """Collect the notes/visual-recommendation lines for a slide's notes frame."""
    parts: list[str] = []
    for note in slide.speaker_notes[:MAX_BULLETS_PER_SLIDE]:
        cleaned = _clean_line(note)
        if cleaned:
            parts.append(_truncate(cleaned))
    if slide.visual_recommendation:
        parts.append(
            f"Visual recommendation: {_truncate(_clean_line(slide.visual_recommendation))}"
        )
    return parts


def _clean_line(value: object) -> str:
    """Normalize a rendered value to a single trimmed line.

    Multi-line strings are collapsed to a single line so each paragraph stays
    deterministic (no embedded newline splitting one bullet across lines).
    """
    text = str(value or "").strip()
    return " ".join(text.splitlines())


def _truncate(text: str) -> str:
    """Truncate an over-long line with an ellipsis (defensive bound)."""
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[: MAX_TEXT_LENGTH - 3] + "..."


def parse_pptx(byte_data: bytes) -> Presentation:
    """Parse PPTX bytes back into a python-pptx Presentation (verification)."""
    return Presentation(BytesIO(byte_data))
