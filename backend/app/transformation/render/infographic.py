"""Render a validated Infographic into real PDF and PNG files.

Uses PyMuPDF (``fitz``) to lay out a deterministic infographic on fixed A4
pages: a coloured title banner, a key-messages block, per-section blocks
(heading / message / optional visual suggestion) and a layout-recommendation
footer.  The same canonical layout is exported both as PDF bytes and as PNG
image bytes so the two formats always agree on content.

Phase 8C hardening (mirrors Phase 8A/8B):
  * Rendering remains deterministic and LLM-free — it consumes the validated
    ``Infographic`` Pydantic model directly and never invokes a language model.
  * Fixed A4 geometry and base-14 PDF fonts keep layout stable across hosts.
  * Every rendered line is drawn individually with measured greedy word-wrap,
    so wrapped content is never dropped (no silent content loss); when a line
    would pass the printable area a fresh page is started.
  * Defensive guards inherited from the 8B normalizer: long strings are
    truncated, embedded newlines are collapsed to a single line, and empty
    optional collections are skipped safely.
  * ``Infographic`` is the PNG-primary artifact: exactly one rasterized page
    is returned when it fits on a single page, and multi-page infographics are
    composited into one tall image so no page is dropped from the PNG.
  * ``parse_infographic_pdf()`` round-trip verification is preserved.

Only the bundled PyMuPDF library is used (no new dependencies).
"""

from __future__ import annotations

import fitz

from app.transformation.output_schemas import Infographic
from app.transformation.render._documents import (
    MAX_LINES_PER_SECTION,
    clean_line,
    truncate,
)
from app.transformation.render.pdf import PDF_MIME_TYPE

INF_PNG_MIME_TYPE = "image/png"

# A4 page geometry in points (595 x 842).  All values are fixed so layout stays
# deterministic and independent of the host environment.
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 50
MARGIN_RIGHT = 50
MARGIN_TOP = 50
MARGIN_BOTTOM = 50

# Vertical padding inside a coloured banner/band, and gap after a block.
BAND_PADDING = 4.0
BLOCK_GAP = 4.0

TITLE_FONT_SIZE = 20
HEADING_FONT_SIZE = 13
BODY_FONT_SIZE = 11
# Basic 14 PDF fonts avoid embedding/downloading font files (deterministic).
TITLE_FONT = "hebo"  # Helvetica Bold
HEADING_FONT = "hebo"
BODY_FONT = "helv"
# Multiplicative leading so line spacing scales with font size.
LINE_HEIGHT_FACTOR = 1.2
# Small safety slack so measured width never exceeds the wrappable space.
WRAP_SLACK = 4.0
# ASCII bullet (the U+2022 bullet is not in the base-14 Helvetica encoding and
# would extract as a replacement character; a hyphen keeps extracted text clean).
BULLET_PREFIX = "- "

# Fixed palette (deep navy accents on white) rendered through fitz primitives.
ACCENT = (0.13, 0.21, 0.38)
ACCENT_TEXT = (1.0, 1.0, 1.0)
BODY_COLOR = (0.0, 0.0, 0.0)

# Fixed raster DPI so PNG output is reproducible.
PNG_DPI = 150

# Human-facing band headings used by the deterministic layout.
_KEY_MESSAGES_HEADING = "KEY MESSAGES"
_LAYOUT_HEADING = "LAYOUT RECOMMENDATION"


def render_infographic_pdf(infographic: Infographic) -> bytes:
    """Render an Infographic into PDF bytes."""
    _validate(infographic)
    return _build_document(infographic).tobytes()


def render_infographic_png(
    infographic: Infographic,
    dpi: int = PNG_DPI,
) -> bytes:
    """Render an Infographic into PNG image bytes.

    A single-page infographic is rasterized directly.  A multi-page one is
    composited into one tall image (pages stacked top to bottom) so the PNG
    never silently drops content.
    """
    _validate(infographic)
    document = _build_document(infographic)
    pixmaps = [page.get_pixmap(dpi=dpi) for page in document]
    if len(pixmaps) == 1:
        return pixmaps[0].tobytes("png")

    tall = fitz.open()
    tall_page = tall.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT * len(pixmaps))
    for index, pixmap in enumerate(pixmaps):
        tall_page.insert_image(
            fitz.Rect(
                0,
                PAGE_HEIGHT * index,
                PAGE_WIDTH,
                PAGE_HEIGHT * (index + 1),
            ),
            stream=pixmap.tobytes("png"),
        )
    return tall_page.get_pixmap(dpi=dpi).tobytes("png")


def _validate(infographic: Infographic) -> None:
    """Defensive guard for callers that bypass schema validation."""
    if not infographic.key_messages or not infographic.sections:
        raise ValueError("Infographic requires key messages and at least one section.")


def _build_document(infographic: Infographic) -> fitz.Document:
    """Lay out the infographic into a deterministic multi-page PDF document."""
    document = fitz.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    max_y = PAGE_HEIGHT - MARGIN_BOTTOM
    baseline = MARGIN_TOP + TITLE_FONT_SIZE * LINE_HEIGHT_FACTOR

    # Title banner.
    page, baseline = _draw_band(
        document, page, baseline, _clean(infographic.title),
        TITLE_FONT_SIZE, TITLE_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=8.0, gap=10.0,
    )

    # Key messages block.
    page, baseline = _draw_band(
        document, page, baseline, _KEY_MESSAGES_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    for message in infographic.key_messages[:MAX_LINES_PER_SECTION]:
        page, baseline = _draw_paragraph(
            document, page, baseline, f"{BULLET_PREFIX}{_clean(message)}",
            BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
        )

    # Per-section blocks.
    for section in infographic.sections[:MAX_LINES_PER_SECTION]:
        page, baseline = _draw_band(
            document, page, baseline, _clean(section.heading),
            HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
            width, max_y, padding=BAND_PADDING, gap=2.0,
        )
        page, baseline = _draw_paragraph(
            document, page, baseline, f"{BULLET_PREFIX}{_clean(section.message)}",
            BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
        )
        if section.visual_suggestion:
            cleaned = _clean(section.visual_suggestion)
            if cleaned:
                page, baseline = _draw_paragraph(
                    document, page, baseline, f"[Visual: {cleaned}]",
                    BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
                )

    # Layout-recommendation footer.
    page, baseline = _draw_band(
        document, page, baseline, _LAYOUT_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    page, baseline = _draw_paragraph(
        document, page, baseline, _clean(infographic.layout_recommendation),
        BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
    )
    for suggestion in infographic.visual_suggestions[:MAX_LINES_PER_SECTION]:
        cleaned = _clean(suggestion)
        if cleaned:
            page, baseline = _draw_paragraph(
                document, page, baseline, f"{BULLET_PREFIX}{cleaned}",
                BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
            )

    return document


def _clean(value: object) -> str:
    """Normalize a rendered value to a single trimmed, capped line."""
    return truncate(clean_line(value))


def _draw_band(
    document: fitz.Document,
    page: fitz.Page,
    baseline: float,
    text: str,
    fontsize: float,
    fontname: str,
    fill: tuple[float, float, float],
    textcolor: tuple[float, float, float],
    width: float,
    max_y: float,
    *,
    padding: float,
    gap: float,
) -> tuple[fitz.Page, float]:
    """Draw a coloured band of text, returning the next baseline position.

    The band rectangle grows with its wrapped content; when a line would pass
    the printable area the current page's band is finalized and the remaining
    lines continue on a fresh page.  Rects are drawn before text so extracted
    text stays clean while the PNG shows the accent bar.
    """
    text = text.strip()
    if not text:
        return page, baseline + gap

    line_height = fontsize * LINE_HEIGHT_FACTOR
    lines = _wrap(text, fontname, fontsize, width - 2 * padding)

    band_top = baseline
    y = baseline
    for line in lines:
        if y + line_height > max_y:
            page.draw_rect(
                fitz.Rect(MARGIN_LEFT, band_top - line_height, MARGIN_LEFT + width, y + 2),
                color=fill,
                fill=fill,
            )
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN_TOP + line_height
            band_top = y
        page.insert_text(
            (MARGIN_LEFT + padding, y),
            line,
            fontsize=fontsize,
            fontname=fontname,
            color=textcolor,
        )
        y += line_height

    page.draw_rect(
        fitz.Rect(MARGIN_LEFT, band_top - line_height, MARGIN_LEFT + width, y + 2),
        color=fill,
        fill=fill,
    )
    return page, y + gap


def _draw_paragraph(
    document: fitz.Document,
    page: fitz.Page,
    baseline: float,
    text: str,
    fontsize: float,
    fontname: str,
    color: tuple[float, float, float],
    width: float,
    max_y: float,
    *,
    gap: float,
) -> tuple[fitz.Page, float]:
    """Draw a wrapped paragraph, returning the next baseline position.

    Each physical line is drawn individually with ``insert_text`` so no content
    is dropped even when a paragraph exceeds a single page; a new page is
    created only when the next line would pass the printable area.
    """
    text = text.strip()
    if not text:
        return page, baseline

    line_height = fontsize * LINE_HEIGHT_FACTOR
    for physical_line in _wrap(text, fontname, fontsize, width):
        if baseline + line_height > max_y:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            baseline = MARGIN_TOP + line_height
        page.insert_text(
            (MARGIN_LEFT, baseline),
            physical_line,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
        )
        baseline += line_height
    return page, baseline + gap


def _wrap(text: str, fontname: str, fontsize: float, width: float) -> list[str]:
    """Break ``text`` into physical lines that fit within ``width``.

    Greedy word-wrap measured with ``get_text_length``.  A single word wider
    than the line is hard-split so even pathological input produces bounded
    lines instead of overflowing the page edge.
    """
    space_w = fitz.get_text_length(" ", fontname, fontsize)
    avail_width = width - WRAP_SLACK

    lines: list[str] = []
    current = ""
    current_w = 0.0

    for word in text.split(" "):
        if word == "":
            continue
        word_w = fitz.get_text_length(word, fontname, fontsize)
        if current and (current_w + space_w + word_w) <= avail_width:
            current += " " + word
            current_w += space_w + word_w
        else:
            if current:
                lines.append(current)
                current = ""
                current_w = 0.0
            if word_w <= avail_width:
                current = word
                current_w = word_w
            else:
                # Over-wide word: hard-split into fitting chunks.
                pieces = _chunk_word(word, fontname, fontsize, avail_width)
                for piece in pieces[:-1]:
                    lines.append(piece)
                current = pieces[-1]
                current_w = fitz.get_text_length(current, fontname, fontsize)

    if current:
        lines.append(current)
    return lines


def _chunk_word(
    word: str,
    fontname: str,
    fontsize: float,
    avail_width: float,
) -> list[str]:
    """Split a single over-wide word into character chunks that fit the line."""
    chunks: list[str] = []
    buffer = ""
    for char in word:
        trial = buffer + char
        if (not buffer) or fitz.get_text_length(trial, fontname, fontsize) <= avail_width:
            buffer = trial
        else:
            chunks.append(buffer)
            buffer = char
    if buffer:
        chunks.append(buffer)
    return chunks


def parse_infographic_pdf(byte_data: bytes) -> fitz.Document:
    """Parse PDF bytes back into a PyMuPDF Document (verification)."""
    return fitz.open(stream=byte_data, filetype="pdf")


__all__ = [
    "INF_PNG_MIME_TYPE",
    "PDF_MIME_TYPE",
    "PNG_DPI",
    "parse_infographic_pdf",
    "render_infographic_pdf",
    "render_infographic_png",
]