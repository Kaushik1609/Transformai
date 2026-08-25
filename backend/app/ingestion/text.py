"""Text normalization and deterministic chunking utilities."""

from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_text(content: str) -> str:
    """Normalize line endings, horizontal whitespace, and blank lines."""
    if not isinstance(content, str):
        raise TypeError("Text content must be a string.")

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(_WHITESPACE_RE.sub(" ", line).strip() for line in normalized.split("\n"))
    normalized = _NEWLINE_RE.sub("\n\n", normalized)
    return normalized.strip()


def chunk_text(content: str, *, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split normalized text into ordered, character-based chunks."""
    normalized = normalize_text(content)
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("Overlap must be non-negative and smaller than chunk size.")

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = end - overlap
    return chunks
