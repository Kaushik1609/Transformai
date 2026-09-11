"""
TransformIQ Backend — Deterministic PII Detection & Redaction (Phase 11K)

A conservative, offline PII classifier used for log/surface hygiene.  It
detects well-formed directly identifiable values:

- email addresses
- phone-like numbers (7+ digits with optional country code / separators)
- IPv4 addresses
- credit-card-like numbers (Luhn-valid, NOT the full list — representative rules)

Patterns are deliberately strict to avoid false positives on prose.  PII
detection NEVER causes source artifacts to be rewritten; storage keeps the
original file untouched.  Redaction is applied to logs, events and error
messages only.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(\d{1,4}\)[\s-]?)?"
    r"\d{3,4}[\s-]?\d{3,4}(?:[\s-]?\d{2,4})?(?!\d)",
)

# NOTE: separators exclude '.' on purpose so IPv4 addresses are never folded
# into phone matches.

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


class Luhn:
    """Minimal Luhn check for card-like numbers."""

    @staticmethod
    def valid(number: str) -> bool:
        digits = [int(c) for c in number if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        total = 0
        parity = len(digits) % 2
        for i, digit in enumerate(digits):
            if i % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0


@dataclass(frozen=True)
class PIIFinding:
    """One PII hit: category plus a redacted snippet (never the raw value)."""

    category: str
    redacted_snippet: str


_MASK = "[PII:X]"


def detect_pii(text: str) -> list[PIIFinding]:
    """Return deterministic, non-overlapping PII findings.

    Classification order (email → ipv4 → credit_card → phone) plus progressive
    masking guarantees a value is reported under exactly one category and a
    phone pattern never double-flags an IP address or card number.
    """
    if not text:
        return []
    findings: list[PIIFinding] = []
    masked = text

    def apply(
        label: str,
        pattern: re.Pattern,
        *,
        valid: Callable[[str], bool] | None = None,
    ) -> None:
        nonlocal masked
        for match in pattern.finditer(masked):
            value = match.group(0)
            if valid is not None and not valid(value):
                continue
            findings.append(PIIFinding(category=label, redacted_snippet=f"[PII:{label.upper()}]"))
        if valid is not None:
            masked = pattern.sub(
                lambda m: m.group(0) if not valid(m.group(0)) else _MASK, masked
            )
        else:
            masked = pattern.sub(_MASK, masked)

    apply("email", _EMAIL_RE)
    apply("ipv4", _IPV4_RE)
    apply("credit_card", _CC_RE, valid=Luhn.valid)
    apply("phone", _PHONE_RE)
    return findings


def redact_pii(text: str) -> str:
    """Replace detected PII values with category markers."""
    if not text:
        return text
    redacted = _EMAIL_RE.sub("[PII:EMAIL]", text)
    # IPs before phones/CCs so dotted hosts are never folded into numbers.
    redacted = _IPV4_RE.sub("[PII:IP]", redacted)

    def _cc(match: re.Match) -> str:
        if Luhn.valid(match.group(0)):
            return "[PII:CC]"
        return match.group(0)

    redacted = _CC_RE.sub(_cc, redacted)
    redacted = _PHONE_RE.sub("[PII:PHONE]", redacted)
    return redacted


__all__ = ["PIIFinding", "detect_pii", "redact_pii"]