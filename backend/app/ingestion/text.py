"""Text normalization and deterministic chunking utilities."""

from __future__ import annotations

import re
from typing import Any


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


def _find_boundary(text: str, start: int, max_end: int, min_split: int) -> int:
    """Find a natural semantic break point between min_split and max_end."""
    slice_text = text[min_split:max_end]
    if not slice_text:
        return max_end

    # 1. Paragraph boundary
    p_idx = slice_text.rfind("\n\n")
    if p_idx != -1:
        return min_split + p_idx + 2

    # 2. Sentence boundary
    best_sent = -1
    for punct in (". ", "! ", "? "):
        idx = slice_text.rfind(punct)
        if idx > best_sent:
            best_sent = idx + 1
    if best_sent != -1:
        return min_split + best_sent

    # 3. Newline
    nl_idx = slice_text.rfind("\n")
    if nl_idx != -1:
        return min_split + nl_idx + 1

    # 4. Word break
    sp_idx = slice_text.rfind(" ")
    if sp_idx != -1:
        return min_split + sp_idx + 1

    return max_end


def chunk_text_with_metadata(
    content: str,
    *,
    chunk_size: int = 1000,
    overlap: int = 100,
) -> list[dict[str, Any]]:
    """Split normalized text into ordered chunks with boundary awareness and offsets.

    Returns a list of dicts with:
        content: str
        char_start: int
        char_end: int
        char_count: int
    """
    normalized = normalize_text(content)
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("Overlap must be non-negative and smaller than chunk size.")

    chunks: list[dict[str, Any]] = []
    start = 0
    total_len = len(normalized)

    while start < total_len:
        max_end = min(start + chunk_size, total_len)
        if max_end == total_len:
            split_end = max_end
        else:
            min_split = max(start + (chunk_size // 2), start + 1)
            split_end = _find_boundary(normalized, start, max_end, min_split)

        chunk_str = normalized[start:split_end].strip()
        if chunk_str:
            chunks.append(
                {
                    "content": chunk_str,
                    "char_start": start,
                    "char_end": split_end,
                    "char_count": len(chunk_str),
                }
            )

        if split_end >= total_len:
            break

        next_start = max(start + 1, split_end - overlap)
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


def chunk_text(content: str, *, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split normalized text into ordered, boundary-aware chunks."""
    return [c["content"] for c in chunk_text_with_metadata(content, chunk_size=chunk_size, overlap=overlap)]
