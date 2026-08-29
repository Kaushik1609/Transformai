"""Render document outputs (Executive Summary, Advisory) into real .pdf files.

Uses PyMuPDF (``fitz``) to lay out a title plus labelled sections with
bulleted content onto A4 pages.  Returns the file bytes so the caller can
persist them through the storage abstraction.

Phase 8B hardening:
  * Rendering remains deterministic and LLM-free — it consumes the validated
    Pydantic models directly via the shared section normalizer and never
    invokes a language model.
  * Long titles / section lines are truncated defensively so a single
    pathological string cannot explode a page.
  * Multi-line list items are collapsed to a single line per paragraph so
    layout stays deterministic.
  * Paragraphs are word-wrapped manually (measured with ``get_text_length``)
    and drawn with ``insert_text``, so wrapped content is never dropped and no
    over-tall paragraph is silently discarded.  When a line would pass the
    printable area a fresh page is started.
  * Empty optional collections are skipped safely.
  * ``parse_pdf()`` round-trip verification is preserved.
  * Only the bundled PyMuPDF library is used (no new dependencies).
"""

from __future__ import annotations

from io import BytesIO

import fitz

from app.transformation.output_schemas import Advisory, ExecutiveSummary
from app.transformation.render._documents import (
    advisory_sections,
    executive_summary_sections,
)

PDF_MIME_TYPE = "application/pdf"

# A4 page geometry in points (595 x 842).  All values are fixed so layout stays
# deterministic and independent of the host environment.
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 50
MARGIN_RIGHT = 50
MARGIN_TOP = 50
MARGIN_BOTTOM = 50

TITLE_FONT_SIZE = 16
HEADING_FONT_SIZE = 13
BODY_FONT_SIZE = 11
# Basic 14 PDF fonts avoid embedding/downloading font files (deterministic).
TITLE_FONT = "hebo"  # Helvetica Bold
HEADING_FONT = "hebo"
BODY_FONT = "helv"
# Multiplicative leading so line spacing scales with font size.
LINE_HEIGHT_FACTOR = 1.2
# Small safety slack so measured width never exceeds the awrappable space.
WRAP_SLACK = 4.0
# ASCII bullet (the U+2022 bullet is not in the base-14 Helvetica encoding and
# would extract as a replacement character; a hyphen keeps extracted text clean).
BULLET_PREFIX = "- "


def render_executive_summary_pdf(summary: ExecutiveSummary) -> bytes:
    """Render an ExecutiveSummary into PDF bytes."""
    return _render_pdf(executive_summary_sections(summary))


def render_advisory_pdf(advisory: Advisory) -> bytes:
    """Render an Advisory into PDF bytes."""
    return _render_pdf(advisory_sections(advisory))


def _render_pdf(sections: list[tuple[str | None, list[str]]]) -> bytes:
    """Render normalized sections into a deterministic multi-page PDF."""
    document = fitz.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    cursor = MARGIN_TOP + BODY_FONT_SIZE * LINE_HEIGHT_FACTOR
    printable_width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    max_y = PAGE_HEIGHT - MARGIN_BOTTOM

    for index, (heading, lines) in enumerate(sections):
        if index == 0:
            # Leading section carries the title with a None heading.
            for title_line in lines:
                page, cursor = _write_paragraph(
                    document, page, cursor, title_line,
                    TITLE_FONT_SIZE, TITLE_FONT, printable_width, max_y,
                )
            continue

        if heading is not None:
            page, cursor = _write_paragraph(
                document, page, cursor, heading,
                HEADING_FONT_SIZE, HEADING_FONT, printable_width, max_y,
            )
        for line in lines:
            page, cursor = _write_paragraph(
                document, page, cursor, f"{BULLET_PREFIX}{line}",
                BODY_FONT_SIZE, BODY_FONT, printable_width, max_y,
            )

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _write_paragraph(
    document: fitz.Document,
    page: fitz.Page,
    baseline: float,
    text: str,
    fontsize: float,
    fontname: str,
    width: float,
    max_y: float,
) -> tuple[fitz.Page, float]:
    """Draw a wrapped paragraph, returning the next baseline position.

    Each physical line is drawn individually with ``insert_text`` so no content
    is dropped even when a paragraph exceeds a single page; a new page is
    created only when the next line would pass the printable area.
    """
    line_height = fontsize * LINE_HEIGHT_FACTOR
    y = baseline
    for physical_line in _wrap(text, fontname, fontsize, width):
        if y > max_y:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN_TOP + line_height
        page.insert_text(
            (MARGIN_LEFT, y),
            physical_line,
            fontsize=fontsize,
            fontname=fontname,
        )
        y += line_height
    return page, y


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


def parse_pdf(byte_data: bytes) -> fitz.Document:
    """Parse PDF bytes back into a PyMuPDF Document (verification)."""
    return fitz.open(stream=byte_data, filetype="pdf")


__all__ = [
    "PDF_MIME_TYPE",
    "parse_pdf",
    "render_advisory_pdf",
    "render_executive_summary_pdf",
]
