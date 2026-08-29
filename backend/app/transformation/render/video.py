"""Render a validated VideoPackage into a structured PDF package document and
an SRT subtitle companion file.

The MVP video deliverable is the PRD-defined structured video package (title,
script, storyboard, scenes, narration, subtitles, visual recommendations) —
NOT a playable MP4.  This renderer deterministically consumes the validated
``VideoPackage`` Pydantic model and produces:

* PDF — a fixed-layout structured package document (`application/pdf`) that a
  reviewer can read and that mirrors the Phase 8B/8C hardened document style.
* SRT — one subtitle cue per storyboard scene in scene order
  (`application/x-subrip`), timed deterministically from subtitle length.

Phase 8D hardening (mirrors Phases 8A/8B/8C):
  * Rendering is deterministic and LLM-free — it consumes the validated
    ``VideoPackage`` directly and never invokes a language model.
  * Fixed A4 geometry, base-14 PDF fonts and a fixed accent palette keep the
    layout stable across hosts.
  * Every rendered line is drawn individually with measured greedy word-wrap,
    so wrapped content is never silently dropped; a fresh page starts when the
    next line would pass the printable area.
  * Defensive guards inherited from the 8B normalizer: long strings are
    truncated, embedded newlines are collapsed/regrouped to bounded lines, and
    empty optional fields are skipped (no orphan "Visual:" labels).
  * ``parse_video_package_pdf()`` / ``parse_video_package_srt()`` round-trip
    verification helpers are provided.

SRT timing is a deterministic heuristic, NOT audio-backed: the schema carries
no real audio duration, so each cue is timed from the length of its normalized
subtitle at a fixed character rate (``SUBTITLE_CHARS_PER_SECOND``) using
integer millisecond arithmetic (no floating-point drift).  Cues start at
00:00:00,000, have positive duration, are strictly chronological, and each
next cue begins exactly where the previous ended.

Only the bundled PyMuPDF library is used (no new dependencies).
"""

from __future__ import annotations

import math
import re

import fitz

from app.transformation.output_schemas import VideoPackage, VideoScene
from app.transformation.render._documents import (
    MAX_LINES_PER_SECTION,
    clean_line,
    truncate,
)
from app.transformation.render.pdf import PDF_MIME_TYPE

SRT_MIME_TYPE = "application/x-subrip"

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

# ---------------------------------------------------------------------------
# Deterministic subtitle timing heuristic (NOT audio-backed)
# ---------------------------------------------------------------------------
# The VideoPackage schema carries no real audio duration, so each scene's SRT
# cue is timed from the length of its normalized subtitle at this fixed rate.
# Character rate in characters per second; the minimum duration guards against
# zero-length cues.  All arithmetic is integer-millisecond so the output is
# byte-deterministic and host-independent.
SUBTITLE_CHARS_PER_SECOND = 15.0
MIN_SUBTITLE_DURATION_MS = 1000

# Human-facing section headings used by the deterministic layout (ASCII so the
# base-14 Helvetica encodings extract cleanly).
_SCRIPT_HEADING = "SCRIPT"
_STORYBOARD_HEADING = "STORYBOARD"
_NARRATION_HEADING = "NARRATION"
_SUBTITLES_HEADING = "SUBTITLES"
_VISUAL_HEADING = "VISUAL RECOMMENDATIONS"

_LABEL_DESCRIPTION = "Description:"
_LABEL_NARRATION = "Narration:"
_LABEL_SUBTITLE = "Subtitle:"
_LABEL_VISUAL = "Visual recommendation:"


def render_video_package_pdf(video_package: VideoPackage) -> bytes:
    """Render a validated VideoPackage into a structured PDF document."""
    _validate(video_package)
    return _build_document(video_package).tobytes()


def render_video_package_srt(video_package: VideoPackage) -> bytes:
    """Render a validated VideoPackage into deterministic SRT subtitle bytes.

    One cue per storyboard scene, in scene order.  Timing is a deterministic
    heuristic derived from the normalized subtitle length (see module docs).
    """
    _validate(video_package)
    lines: list[str] = []
    cue_number = 1
    cursor_ms = 0
    for scene in video_package.storyboard:
        subtitle = _clean(scene.subtitle)
        duration_ms = _cue_duration_ms(subtitle)
        start_ms = cursor_ms
        end_ms = cursor_ms + duration_ms
        lines.append(str(cue_number))
        lines.append(f"{_format_timestamp(start_ms)} --> {_format_timestamp(end_ms)}")
        lines.append(subtitle)
        lines.append("")
        cue_number += 1
        cursor_ms = end_ms
    return "\n".join(lines).encode("utf-8")


def parse_video_package_pdf(byte_data: bytes) -> fitz.Document:
    """Parse PDF bytes back into a PyMuPDF Document (verification)."""
    return fitz.open(stream=byte_data, filetype="pdf")


def parse_video_package_srt(byte_data: bytes) -> list[tuple[int, int, str]]:
    """Parse SRT bytes into ordered ``(start_ms, end_ms, text)`` cues."""
    text = byte_data.decode("utf-8")
    cues: list[tuple[int, int, str]] = []
    for block in re.split(r"\n\s*\n", text.strip("\n")):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if len(lines) < 2 or not lines[0].strip().isdigit():
            continue
        timing = lines[1].split("-->")
        if len(timing) != 2:
            continue
        start = _parse_timestamp_ms(timing[0].strip())
        end = _parse_timestamp_ms(timing[1].strip())
        if start is None or end is None:
            continue
        body = "\n".join(lines[2:]).strip()
        cues.append((start, end, body))
    return cues


def _validate(video_package: VideoPackage) -> None:
    """Defensive guard for callers that bypass schema validation."""
    if not video_package.storyboard:
        raise ValueError("Video package requires at least one storyboard scene.")
    if not video_package.title or not str(video_package.title).strip():
        raise ValueError("Video package requires a title.")
    if not video_package.script or not str(video_package.script).strip():
        raise ValueError("Video package requires a script.")
    if not video_package.narration_full or not str(video_package.narration_full).strip():
        raise ValueError("Video package requires full narration.")
    if not video_package.subtitles_full or not str(video_package.subtitles_full).strip():
        raise ValueError("Video package requires full subtitles.")


# ---------------------------------------------------------------------------
# Deterministic PDF layout
# ---------------------------------------------------------------------------

def _build_document(video_package: VideoPackage) -> fitz.Document:
    """Lay out the video package into a deterministic multi-page PDF document."""
    document = fitz.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    width = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    max_y = PAGE_HEIGHT - MARGIN_BOTTOM
    baseline = MARGIN_TOP + TITLE_FONT_SIZE * LINE_HEIGHT_FACTOR

    # 1. Title banner.
    page, baseline = _draw_band(
        document, page, baseline, _clean(video_package.title),
        TITLE_FONT_SIZE, TITLE_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=8.0, gap=10.0,
    )

    # 2. Script section.
    page, baseline = _draw_band(
        document, page, baseline, _SCRIPT_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    for paragraph in _paragraphs(video_package.script):
        page, baseline = _draw_paragraph(
            document, page, baseline, paragraph,
            BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=4.0,
        )

    # 3. Storyboard section with one structured block per scene.
    page, baseline = _draw_band(
        document, page, baseline, _STORYBOARD_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    for index, scene in enumerate(
        video_package.storyboard[:MAX_LINES_PER_SECTION], start=1
    ):
        page, baseline = _draw_scene_block(
            document, page, baseline, scene, index, width, max_y,
        )

    # 4. Narration section.
    page, baseline = _draw_band(
        document, page, baseline, _NARRATION_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    for paragraph in _paragraphs(video_package.narration_full):
        page, baseline = _draw_paragraph(
            document, page, baseline, paragraph,
            BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=4.0,
        )

    # 5. Subtitles section.
    page, baseline = _draw_band(
        document, page, baseline, _SUBTITLES_HEADING,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=4.0,
    )
    for paragraph in _paragraphs(video_package.subtitles_full):
        page, baseline = _draw_paragraph(
            document, page, baseline, paragraph,
            BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=4.0,
        )

    # 6. Visual Recommendations section (skipped entirely when empty).
    if video_package.visual_recommendations:
        page, baseline = _draw_band(
            document, page, baseline, _VISUAL_HEADING,
            HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
            width, max_y, padding=BAND_PADDING, gap=4.0,
        )
        for rec in video_package.visual_recommendations[:MAX_LINES_PER_SECTION]:
            cleaned = _clean(rec)
            if cleaned:
                page, baseline = _draw_paragraph(
                    document, page, baseline, f"{BULLET_PREFIX}{cleaned}",
                    BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=2.0,
                )

    return document


def _draw_scene_block(
    document: fitz.Document,
    page: fitz.Page,
    baseline: float,
    scene: VideoScene,
    index: int,
    width: float,
    max_y: float,
) -> tuple[fitz.Page, float]:
    """Draw one storyboard scene block, returning the next baseline position.

    The scene heading is a coloured band (``Scene N - <title>``); each field is
    a bold label line followed by its normalized content.  An empty optional
    ``visual_recommendation`` is skipped entirely (no orphan label).
    """
    title = _clean(scene.title)
    heading = f"Scene {index} - {title}" if title else f"Scene {index}"
    page, baseline = _draw_band(
        document, page, baseline, heading,
        HEADING_FONT_SIZE, HEADING_FONT, ACCENT, ACCENT_TEXT,
        width, max_y, padding=BAND_PADDING, gap=2.0,
    )
    page, baseline = _draw_label(
        document, page, baseline, _LABEL_DESCRIPTION, scene.description,
        width, max_y, gap=2.0,
    )
    page, baseline = _draw_label(
        document, page, baseline, _LABEL_NARRATION, scene.narration,
        width, max_y, gap=2.0,
    )
    page, baseline = _draw_label(
        document, page, baseline, _LABEL_SUBTITLE, scene.subtitle,
        width, max_y, gap=2.0,
    )
    if _clean(scene.visual_recommendation):
        page, baseline = _draw_label(
            document, page, baseline, _LABEL_VISUAL, scene.visual_recommendation,
            width, max_y, gap=2.0,
        )
    return page, baseline


def _draw_label(
    document: fitz.Document,
    page: fitz.Page,
    baseline: float,
    label: str,
    value: object,
    width: float,
    max_y: float,
    *,
    gap: float,
) -> tuple[fitz.Page, float]:
    """Draw a bold label line followed by its normalized value paragraph."""
    cleaned = _clean(value)
    if not cleaned:
        return page, baseline
    page, baseline = _draw_paragraph(
        document, page, baseline, label,
        BODY_FONT_SIZE, HEADING_FONT, ACCENT, width, max_y, gap=0,
    )
    page, baseline = _draw_paragraph(
        document, page, baseline, cleaned,
        BODY_FONT_SIZE, BODY_FONT, BODY_COLOR, width, max_y, gap=gap,
    )
    return page, baseline


def _paragraphs(value: object) -> list[str]:
    """Normalize free text into capped single-line paragraphs.

    Consecutive non-empty lines are joined into one paragraph so embedded
    newlines inside a paragraph collapse to a single rendered line (consistent
    with the Phase 8B/8C normalizer); blank lines separate paragraphs.  Each
    paragraph is truncated defensively and the total is capped so degenerate
    output cannot create an unbounded number of paragraphs.
    """
    groups: list[str] = []
    current: list[str] = []
    for line in str(value or "").splitlines():
        line = line.strip()
        if line:
            current.append(line)
        elif current:
            groups.append(" ".join(current))
            current = []
    if current:
        groups.append(" ".join(current))
    paragraphs = [truncate(clean_line(p)) for p in groups]
    return [p for p in paragraphs if p][:MAX_LINES_PER_SECTION]


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
    text stays clean while the PDF shows the accent bar.
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


# ---------------------------------------------------------------------------
# Deterministic SRT timing helpers
# ---------------------------------------------------------------------------

def _cue_duration_ms(subtitle: str) -> int:
    """Return a deterministic positive cue duration in integer milliseconds.

    Derived purely from the normalized subtitle length at the fixed character
    rate, floored at ``MIN_SUBTITLE_DURATION_MS``.
    """
    return max(
        MIN_SUBTITLE_DURATION_MS,
        math.ceil((len(subtitle) / SUBTITLE_CHARS_PER_SECOND) * 1000),
    )


def _format_timestamp(ms: int) -> str:
    """Format integer milliseconds as SRT ``HH:MM:SS,mmm`` (zero-padded)."""
    ms = int(ms)
    minutes, seconds = divmod(ms // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms % 1000:03d}"


def _parse_timestamp_ms(value: str) -> int | None:
    """Parse an SRT ``HH:MM:SS,mmm`` timestamp into integer milliseconds."""
    try:
        hours, minutes, seconds, millis = (
            int(part) for part in value.replace(",", ":").split(":")
        )
    except (ValueError, AttributeError):
        return None
    return ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis


__all__ = [
    "MIN_SUBTITLE_DURATION_MS",
    "PDF_MIME_TYPE",
    "SRT_MIME_TYPE",
    "SUBTITLE_CHARS_PER_SECOND",
    "parse_video_package_pdf",
    "parse_video_package_srt",
    "render_video_package_pdf",
    "render_video_package_srt",
]