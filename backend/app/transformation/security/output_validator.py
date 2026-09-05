"""Deterministic L5 output-security validator (Phase 11H).

Runs on **already-Pydantic-validated** output structures (the output of the
parser/schema boundary) and answers the L5 question:

    "Is this generated structure/content safe to process / render / persist?"

It returns a structured verdict with machine-readable reason codes:

    valid    — no concerns
    warning  — bounded resource / hygiene concerns (content still processed)
    blocked  — dangerous content that must not be rendered or persisted

The validator is fully deterministic and offline: no LLM, no API calls, no
network, no randomness, no secrets.  It never deletes or rewrites content and
it never includes source text in its messages (only field names and stable
reason codes), so security metadata/logs can never leak document content.

False positives are minimized by design:

  * ordinary URLs (https://..., ...) are never flagged
  * ordinary Markdown / punctuation / prose is never flagged
  * lone mentions of HTML tags or URI schemes in prose are at most a
    ``warning`` (a full executable element or handler stays ``blocked``)
  * size/resource limits are ``warning`` (the renderers already truncate
    defensively), while executable content is ``blocked``

Responsibility split (preserved):
    Parser/Pydantic          -> structural validity
    OutputSecurityValidator  -> content/resource/security validity
    Verification engine      -> grounding/consistency analysis
    Renderers                -> deterministic artifact generation
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

# Verdict statuses (stable public constants).
VALID = "valid"
WARNING = "warning"
BLOCKED = "blocked"

# Severity values used on individual reasons.
SEVERITY_WARNING = "warning"
SEVERITY_BLOCKED = "blocked"

# Machine-readable reason codes (stable public constants).
RE_STRING_TOO_LONG = "string_too_long"
RE_LIST_TOO_LONG = "list_too_long"
RE_NESTED_ITEMS_EXCEEDED = "nested_items_exceeded"
RE_CONTROL_CHARACTER = "control_character"
RE_HTML_SCRIPT = "html_script_tag"
RE_HTML_IFRAME = "html_iframe_tag"
RE_HTML_EVENT_HANDLER = "html_event_handler_attribute"
RE_DANGEROUS_URI_SCHEME = "dangerous_uri_scheme"
RE_TOO_MANY_SLIDES = "too_many_slides"
RE_TOO_MANY_SCENES = "too_many_scenes"
RE_TOO_MANY_INF_SECTIONS = "too_many_infographic_sections"
RE_TOO_MANY_X_THREAD_ITEMS = "too_many_x_thread_items"

# Settings keys consumed by the validator (mirrors app.core.config).
KEY_MAX_STRING_LENGTH = "OUTPUT_MAX_STRING_LENGTH"
KEY_MAX_LIST_LENGTH = "OUTPUT_MAX_LIST_LENGTH"
KEY_MAX_NESTED_ITEMS = "OUTPUT_MAX_NESTED_ITEMS"

# Output-specific structural collection limits (field name -> settings key).
_OUTPUT_COLLECTION_LIMITS: dict[str, tuple[str, str]] = {
    "presentation": ("slides", "OUTPUT_MAX_SLIDES"),
    "video": ("storyboard", "OUTPUT_MAX_VIDEO_SCENES"),
    "infographic": ("sections", "OUTPUT_MAX_INF_SECTIONS"),
    "x": ("thread", "OUTPUT_MAX_X_THREAD_ITEMS"),
}

# ---------------------------------------------------------------------------
# Dangerous-content detectors
# ---------------------------------------------------------------------------

# Control characters that are not ordinary whitespace/formatting.  Newlines,
# carriage returns and tabs are allowed; everything else in the C0 range plus
# DEL is flagged (e.g. NUL injection attempts), but only as a warning.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# A complete <script>...</script> or <iframe>...</iframe> element is an
# executable HTML construct and is blocked.
_SCRIPT_ELEMENT_RE = re.compile(
    r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", re.DOTALL | re.IGNORECASE
)
_IFRAME_ELEMENT_RE = re.compile(
    r"<\s*iframe\b[^>]*>.*?<\s*/\s*iframe\s*>", re.DOTALL | re.IGNORECASE
)
# A lone opening tag without a matching closing pair may simply be textual
# discussion of HTML, so report it as a warning rather than blocking.
_SCRIPT_OPEN_TAG_RE = re.compile(r"<\s*script\b[^>]*?>", re.IGNORECASE)
_IFRAME_OPEN_TAG_RE = re.compile(r"<\s*iframe\b[^>]*?>", re.IGNORECASE)

# An event-handler attribute (onclick=, onerror=, ...) inside an actual tag.
_EVENT_HANDLER_RE = re.compile(
    r"<\s*[a-z][a-z0-9]*\b[^>]*\bon[a-z]+\s*=", re.IGNORECASE
)

# Dangerous URI schemes.  To keep false positives low:
#   - a scheme that is immediately followed by a code payload (any non-space
#     token after the colon, e.g. "javascript:alert(" or
#     "javascript:document.body...") is blocked wherever it appears
#   - a bare "javascript:" mention with nothing (or only whitespace/end)
#     after the colon is treated as prose and stays valid
#   - a scheme used as the value of a URL attribute is always blocked
#   - a data: URI carrying active HTML/SVG content is always blocked
_SCHEME_CODE_RE = re.compile(
    r"(?i)(?:javascript|vbscript)\s*:(?!\s|$)[^\s]*"
)
_HREF_SCHEME_RE = re.compile(
    r"(?i)\b(?:href|src|action|xlink:href)\s*=\s*[\"']?\s*(?:javascript|vbscript)\s*:"
)
_DATA_HTML_RE = re.compile(
    r"(?i)\bdata\s*:\s*(?:text/html|image/svg\+xml|application/xhtml(?:\+xml)?)\b"
)


@dataclass(frozen=True)
class SecurityReason:
    """A single security finding (no source content, no secrets)."""

    code: str
    severity: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field": self.field,
        }


@dataclass(frozen=True)
class SecurityVerdict:
    """Structured outcome of L5 security validation."""

    status: str
    reasons: tuple[SecurityReason, ...] = ()

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    @property
    def blocked_codes(self) -> list[str]:
        return [r.code for r in self.reasons if r.severity == SEVERITY_BLOCKED]

    @property
    def summary(self) -> str:
        """Short, safe, source-free summary (codes + fields only)."""
        if not self.reasons:
            return VALID
        parts = [f"{r.code}({r.field})" if r.field else r.code for r in self.reasons]
        return f"{self.status}: {', '.join(parts)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": [r.to_dict() for r in self.reasons],
            "codes": self.codes,
        }


# ---------------------------------------------------------------------------
# Limits resolution
# ---------------------------------------------------------------------------

def _default_limits() -> dict[str, int]:
    """Resolve limit values from application settings."""
    from app.core.config import settings

    return {
        KEY_MAX_STRING_LENGTH: settings.OUTPUT_MAX_STRING_LENGTH,
        KEY_MAX_LIST_LENGTH: settings.OUTPUT_MAX_LIST_LENGTH,
        KEY_MAX_NESTED_ITEMS: settings.OUTPUT_MAX_NESTED_ITEMS,
        "OUTPUT_MAX_SLIDES": settings.OUTPUT_MAX_SLIDES,
        "OUTPUT_MAX_VIDEO_SCENES": settings.OUTPUT_MAX_VIDEO_SCENES,
        "OUTPUT_MAX_INF_SECTIONS": settings.OUTPUT_MAX_INF_SECTIONS,
        "OUTPUT_MAX_X_THREAD_ITEMS": settings.OUTPUT_MAX_X_THREAD_ITEMS,
    }


def _limit(limits: Mapping[str, int], key: str, default: int) -> int:
    value = limits.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_string(value: str, field: str, limits: Mapping[str, int],
                  reasons: list[SecurityReason]) -> None:
    max_len = _limit(limits, KEY_MAX_STRING_LENGTH, 20000)
    if len(value) > max_len:
        reasons.append(
            SecurityReason(
                RE_STRING_TOO_LONG,
                SEVERITY_WARNING,
                f"Field contains a string longer than the configured maximum.",
                field,
            )
        )
    if _CONTROL_CHAR_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_CONTROL_CHARACTER,
                SEVERITY_WARNING,
                "Field contains characters that are not printable text.",
                field,
            )
        )
    if _SCRIPT_ELEMENT_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_HTML_SCRIPT,
                SEVERITY_BLOCKED,
                "Field contains an executable <script> element.",
                field,
            )
        )
    elif _SCRIPT_OPEN_TAG_RE.search(value):
        # A lone opening tag (no closing pair) may simply be prose about HTML.
        reasons.append(
            SecurityReason(
                RE_HTML_SCRIPT,
                SEVERITY_WARNING,
                "Field references a <script> tag without a matching closing element.",
                field,
            )
        )
    if _IFRAME_ELEMENT_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_HTML_IFRAME,
                SEVERITY_BLOCKED,
                "Field contains an executable <iframe> element.",
                field,
            )
        )
    elif _IFRAME_OPEN_TAG_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_HTML_IFRAME,
                SEVERITY_WARNING,
                "Field references an <iframe> tag without a matching closing element.",
                field,
            )
        )
    if _SCHEME_CODE_RE.search(value) or _HREF_SCHEME_RE.search(value) \
            or _DATA_HTML_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_DANGEROUS_URI_SCHEME,
                SEVERITY_BLOCKED,
                "Field contains an executable URI scheme.",
                field,
            )
        )
    if _EVENT_HANDLER_RE.search(value):
        reasons.append(
            SecurityReason(
                RE_HTML_EVENT_HANDLER,
                SEVERITY_BLOCKED,
                "Field contains an HTML tag with an event-handler attribute.",
                field,
            )
        )


def _walk(value: Any, field: str, limits: Mapping[str, int],
          reasons: list[SecurityReason], nested_count: list[int]) -> None:
    """Recurse over a validated output dict applying generic security rules."""
    max_list = _limit(limits, KEY_MAX_LIST_LENGTH, 500)
    if isinstance(value, str):
        _check_string(value, field, limits, reasons)
        return
    if isinstance(value, list):
        if len(value) > max_list:
            reasons.append(
                SecurityReason(
                    RE_LIST_TOO_LONG,
                    SEVERITY_WARNING,
                    "A collection is larger than the configured maximum.",
                    field,
                )
            )
        nested_count[0] += len(value)
        for item in value:
            _walk(item, field, limits, reasons, nested_count)
        return
    if isinstance(value, dict):
        nested_count[0] += len(value)
        for key, item in value.items():
            _walk(item, key, limits, reasons, nested_count)
        return


def validate_output(
    output_type: str,
    data: Mapping[str, Any],
    *,
    limits: Mapping[str, int] | None = None,
) -> SecurityVerdict:
    """Validate an already-validated output structure (dict view).

    ``output_type`` is one of the seven registered output types and selects
    the output-specific structural limits.  ``data`` MUST already be
    schema-valid (this is a post-parse security check, not a replacement for
    Pydantic validation).
    """
    if limits is None:
        limits = _default_limits()

    reasons: list[SecurityReason] = []
    nested_count: list[int] = [0]

    # Generic string / collection / nesting checks over the whole structure.
    for field, value in data.items():
        _walk(value, field, limits, reasons, nested_count)

    maximum_nested = _limit(limits, KEY_MAX_NESTED_ITEMS, 1000)
    if nested_count[0] > maximum_nested:
        reasons.append(
            SecurityReason(
                RE_NESTED_ITEMS_EXCEEDED,
                SEVERITY_WARNING,
                "The output structure contains more nested items than allowed.",
                None,
            )
        )

    # Output-specific structural limits.
    collection = _OUTPUT_COLLECTION_LIMITS.get(output_type)
    if collection is not None:
        field_name, limit_key = collection
        items = data.get(field_name)
        if isinstance(items, list):
            max_items = _limit(limits, limit_key, 100)
            if len(items) > max_items:
                reasons.append(
                    SecurityReason(
                        _code_for_output_collection(output_type),
                        SEVERITY_WARNING,
                        "The output contains more structured items than allowed.",
                        field_name,
                    )
                )

    return verdict_from_reasons(reasons)


def verdict_from_reasons(reasons: list[SecurityReason]) -> SecurityVerdict:
    """Fold a list of reasons into a single verdict (blocked > warning > valid)."""
    unique: dict[tuple[str, str | None], SecurityReason] = {}
    for reason in reasons:
        key = (reason.code, reason.field)
        # Collisions keep the most severe reason (defense in depth).
        if key not in unique or reason.severity == SEVERITY_BLOCKED:
            unique[key] = reason
    ordered = tuple(unique.values())
    if any(r.severity == SEVERITY_BLOCKED for r in ordered):
        return SecurityVerdict(BLOCKED, ordered)
    if ordered:
        return SecurityVerdict(WARNING, ordered)
    return SecurityVerdict(VALID)


def _code_for_output_collection(output_type: str) -> str:
    return {
        "presentation": RE_TOO_MANY_SLIDES,
        "video": RE_TOO_MANY_SCENES,
        "infographic": RE_TOO_MANY_INF_SECTIONS,
        "x": RE_TOO_MANY_X_THREAD_ITEMS,
    }.get(output_type, RE_LIST_TOO_LONG)


__all__ = [
    "BLOCKED",
    "VALID",
    "WARNING",
    "KEY_MAX_LIST_LENGTH",
    "KEY_MAX_NESTED_ITEMS",
    "KEY_MAX_STRING_LENGTH",
    "RE_CONTROL_CHARACTER",
    "RE_DANGEROUS_URI_SCHEME",
    "RE_HTML_EVENT_HANDLER",
    "RE_HTML_IFRAME",
    "RE_HTML_SCRIPT",
    "RE_LIST_TOO_LONG",
    "RE_NESTED_ITEMS_EXCEEDED",
    "RE_STRING_TOO_LONG",
    "RE_TOO_MANY_INF_SECTIONS",
    "RE_TOO_MANY_SCENES",
    "RE_TOO_MANY_SLIDES",
    "RE_TOO_MANY_X_THREAD_ITEMS",
    "SEVERITY_BLOCKED",
    "SEVERITY_WARNING",
    "SecurityReason",
    "SecurityVerdict",
    "validate_output",
    "verdict_from_reasons",
]