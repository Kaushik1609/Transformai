"""L5 output security — deterministic post-parse validation (Phase 11H).

This package owns the L5 "is this generated content safe to process?"
question.  It is deliberately separate from the Parser/Pydantic boundary
(structural validity), the Verification engine (grounding/consistency) and
the Renderers (deterministic artifact generation).
"""

from app.transformation.security.output_validator import (
    BLOCKED,
    VALID,
    WARNING,
    KEY_MAX_LIST_LENGTH,
    KEY_MAX_NESTED_ITEMS,
    KEY_MAX_STRING_LENGTH,
    RE_CONTROL_CHARACTER,
    RE_DANGEROUS_URI_SCHEME,
    RE_HTML_EVENT_HANDLER,
    RE_HTML_IFRAME,
    RE_HTML_SCRIPT,
    RE_LIST_TOO_LONG,
    RE_NESTED_ITEMS_EXCEEDED,
    RE_STRING_TOO_LONG,
    RE_TOO_MANY_INF_SECTIONS,
    RE_TOO_MANY_SCENES,
    RE_TOO_MANY_SLIDES,
    RE_TOO_MANY_X_THREAD_ITEMS,
    SEVERITY_BLOCKED,
    SEVERITY_WARNING,
    SecurityReason,
    SecurityVerdict,
    validate_output,
    verdict_from_reasons,
)

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