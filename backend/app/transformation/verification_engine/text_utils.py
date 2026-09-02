"""Deterministic text utilities for the Phase 8 verification engine.

Every helper here is pure, offline, and dependency-free so verification can run
in production and in tests without an API key or any network access.  The
routines normalize text, extract content-bearing terms, and pull structured
signals (numbers, percentages, dates) out of generated and source text — these
signals drive claim extraction, evidence matching, and consistency checks.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "nor", "of", "in", "on", "at",
        "to", "for", "with", "by", "from", "up", "down", "over", "under",
        "into", "out", "off", "about", "via", "toward", "towards",
        "is", "are", "was", "were", "be", "been", "being", "am",
        "do", "does", "did", "have", "has", "had", "having",
        "will", "would", "can", "could", "should", "may", "might", "shall",
        "must", "not", "no", "yes", "so", "very", "too", "also", "then",
        "than", "there", "here", "this", "that", "these", "those", "it",
        "its", "as", "we", "our", "you", "your", "they", "their", "he",
        "she", "his", "her", "who", "whom", "what", "which", "when", "where",
        "how", "why", "if", "else", "such", "each", "every", "more", "most",
        "per", "between", "after", "before", "during", "among", "against",
        "both", "either", "neither", "once", "since", "until",
    }
)

# ---------------------------------------------------------------------------
# Number / date patterns
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_PERCENT_RE = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+(?:\.\d+)?)\s*%")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SLASH_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b")

_MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)"
)
_MONTH_YEAR_RE = re.compile(
    rf"\b({_MONTH_NAME})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(19\d{{2}}|20\d{{2}})\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Normalization / tokenization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Lowercase text and collapse all punctuation to single spaces.

    Used for comparing terms between a generated claim and source chunks.
    Pure-numeric tokens survive (with commas removed) so they can be dropped
    from the term set while the original numbers are compared separately.
    """
    lowered = re.sub(r"[^0-9a-z]+", " ", text.lower())
    return re.sub(r"\s+", " ", lowered).strip()


def tokenize(text: str) -> list[str]:
    """Return the normalized word tokens of a string."""
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def meaningful_terms(text: str) -> set[str]:
    """Return content-bearing terms for a string.

    Stopwords, pure numeric tokens, and the deterministic fake-provider
    placeholder are removed so overlap statistics reflect real vocabulary.
    """
    terms: set[str] = set()
    for token in normalize_text(text).split():
        if token in _STOPWORDS:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if token == "deterministic":
            continue
        terms.add(token)
    return terms


# ---------------------------------------------------------------------------
# Number / date extraction
# ---------------------------------------------------------------------------

def extract_numbers(text: str) -> list[float]:
    """Return every numeric value in ``text``, order-preserved and de-duplicated.

    Commas are stripped ("50,000" -> 50000.0) and decimal values are kept.
    """
    if not text:
        return []
    values: list[float] = []
    for match in _NUMBER_RE.findall(text):
        try:
            value = float(match.replace(",", ""))
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return values


def extract_percentages(text: str) -> list[float]:
    """Return numeric values that appear with a percent sign in ``text``."""
    if not text:
        return []
    values: list[float] = []
    for match in _PERCENT_RE.findall(text):
        try:
            value = float(match.replace(",", ""))
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return values


def extract_dates(text: str) -> list[str]:
    """Return canonical date tokens found in ``text``.

    Recognizes ISO dates, slash dates, month/name day-year dates, and bare
    four-digit years.  Canonical forms keep numeric comparison separate from
    date comparison (a year like 2024 is both a number and a date signal).
    """
    if not text:
        return []
    dates: list[str] = []

    def add(value: str) -> None:
        if value and value not in dates:
            dates.append(value)

    for match in _ISO_DATE_RE.findall(text):
        add(match)
    for match in _SLASH_DATE_RE.findall(text):
        add(match)
    for month, day, year in _MONTH_YEAR_RE.findall(text):
        add(f"{month} {day}, {year}".lower())
    for year in _YEAR_RE.findall(text):
        add(year)
    return dates


# ---------------------------------------------------------------------------
# Sentence / bullet splitting
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-*•▪‣◦]|\d+[.)])\s*")


def split_bullets(text: str) -> list[str]:
    """Return bullet items (dash / symbol / numbered) as standalone segments."""
    items: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        match = _BULLET_RE.match(stripped)
        if match:
            items.append(stripped[match.end():].strip())
    return items


def split_sentences(text: str) -> list[str]:
    """Return sentence segments split on terminal punctuation + whitespace.

    Splitting is done per physical line so inline headings (which may carry a
    trailing colon but no terminal punctuation) stay on their own segment
    instead of being merged with the following paragraph's content.
    """
    if not text:
        return []
    segments: list[str] = []
    for raw_line in text.replace("\r", " ").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip()
            if part:
                segments.append(part)
    return segments