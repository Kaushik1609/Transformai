"""Shared, format-agnostic helpers for deterministic DOCX/PDF document rendering.

Phase 8B: document-style outputs (Executive Summary, Advisory) are rendered to
real DOCX and PDF files.  To keep both renderers deterministic, LLM-free and
defensive, each validated schema is normalized here into an ordered list of
sections ``(heading_or_None, lines)``.  The DOCX and PDF renderers then consume
this neutral structure, so the two formats always agree on content and the
hardening rules (truncation, single-line normalization, per-section line caps)
are applied once.

The title is carried as the leading section with a ``None`` heading so the
renderers can style it prominently.
"""

from __future__ import annotations

from app.transformation.output_schemas import Advisory, ExecutiveSummary

# Defensive cap on a single rendered line.  Generous enough that normal content
# is never touched, but bounds pathological long strings so a value cannot bloat
# a document into a massive blob of text.
MAX_TEXT_LENGTH = 2000
# Hard cap on the number of lines rendered per logical section so a degenerate
# output cannot create an unbounded number of paragraphs.
MAX_LINES_PER_SECTION = 500


def truncate(text: str) -> str:
    """Truncate an over-long line with an ellipsis (defensive bound)."""
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[: MAX_TEXT_LENGTH - 3] + "..."


def clean_line(value: object) -> str:
    """Normalize a rendered value to a single trimmed line.

    Multi-line strings are collapsed to a single line so each paragraph stays
    deterministic (no embedded newline splitting one bullet across lines).
    """
    text = str(value or "").strip()
    return " ".join(text.splitlines())


def _section(
    heading: str | None,
    lines: list[str],
) -> tuple[str | None, list[str]]:
    """Build a single cleaned, capped section (heading + lines)."""
    cleaned: list[str] = []
    for line in lines[:MAX_LINES_PER_SECTION]:
        normalized = clean_line(line)
        if normalized:
            cleaned.append(truncate(normalized))
    return heading, cleaned


def executive_summary_sections(
    summary: ExecutiveSummary,
) -> list[tuple[str | None, list[str]]]:
    """Normalize an ExecutiveSummary into ordered, defensive sections."""
    sections: list[tuple[str | None, list[str]]] = [
        _section(None, [summary.title]),
        _section("Summary", [summary.summary]),
    ]
    if summary.context:
        sections.append(_section("Context", [summary.context]))
    if summary.key_findings:
        sections.append(_section("Key Findings", summary.key_findings))
    if summary.key_facts:
        sections.append(_section("Key Facts", summary.key_facts))
    if summary.recommendations:
        sections.append(_section("Recommendations", summary.recommendations))
    if summary.action_items:
        sections.append(_section("Action Items", summary.action_items))
    return sections


def advisory_sections(
    advisory: Advisory,
) -> list[tuple[str | None, list[str]]]:
    """Normalize an Advisory into ordered, defensive sections."""
    sections: list[tuple[str | None, list[str]]] = [
        _section(None, [advisory.title]),
        _section("Situation", [advisory.situation]),
    ]
    if advisory.key_findings:
        sections.append(_section("Key Findings", advisory.key_findings))
    if advisory.impact_risk:
        sections.append(_section("Impact and Risk", advisory.impact_risk))
    if advisory.affected_parties:
        sections.append(_section("Affected Parties", advisory.affected_parties))
    if advisory.recommended_actions:
        sections.append(_section("Recommended Actions", advisory.recommended_actions))
    return sections


__all__ = [
    "MAX_LINES_PER_SECTION",
    "MAX_TEXT_LENGTH",
    "advisory_sections",
    "clean_line",
    "executive_summary_sections",
    "truncate",
]
