"""Validation primitives for supported Phase 3 source inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

SUPPORTED_SOURCE_TYPES = frozenset({"text", "txt", "pdf", "docx"})

MIME_TYPES_BY_SOURCE_TYPE = {
    "text": frozenset({"text/plain"}),
    "txt": frozenset({"text/plain"}),
    "pdf": frozenset({"application/pdf"}),
    "docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }
    ),
}

EXTENSIONS_BY_SOURCE_TYPE = {
    "text": frozenset(),
    "txt": frozenset({".txt"}),
    "pdf": frozenset({".pdf"}),
    "docx": frozenset({".docx"}),
}


class SourceValidationError(ValueError):
    """Raised when source metadata or content violates ingestion rules."""


@dataclass(frozen=True)
class ValidatedSource:
    """Validated source metadata passed to later ingestion stages."""

    source_type: str
    filename: str | None
    mime_type: str
    file_size: int


def validate_source(
    *,
    source_type: str,
    content: bytes,
    filename: str | None = None,
    mime_type: str = "text/plain",
    max_size_bytes: int,
) -> ValidatedSource:
    """Validate a supported source before storage or extraction."""
    normalized_type = source_type.strip().lower()
    if normalized_type not in SUPPORTED_SOURCE_TYPES:
        raise SourceValidationError(
            f"Unsupported source type: {source_type!r}."
        )

    if max_size_bytes < 0:
        raise SourceValidationError("Maximum source size cannot be negative.")

    if not isinstance(content, bytes):
        raise SourceValidationError("Source content must be bytes.")
    if not content:
        raise SourceValidationError("Source content cannot be empty.")
    if len(content) > max_size_bytes:
        raise SourceValidationError(
            f"Source exceeds the maximum size of {max_size_bytes} bytes."
        )

    normalized_mime = mime_type.strip().lower()
    allowed_mimes = MIME_TYPES_BY_SOURCE_TYPE[normalized_type]
    if normalized_mime not in allowed_mimes:
        raise SourceValidationError(
            f"MIME type {mime_type!r} is not valid for {normalized_type!r}."
        )

    if normalized_type != "text":
        if not filename or not filename.strip():
            raise SourceValidationError(
                f"A filename is required for {normalized_type!r} sources."
            )
        extension = PurePath(filename).suffix.lower()
        if extension not in EXTENSIONS_BY_SOURCE_TYPE[normalized_type]:
            raise SourceValidationError(
                f"Filename extension {extension!r} is not valid for "
                f"{normalized_type!r} sources."
            )
    elif filename:
        extension = PurePath(filename).suffix.lower()
        if extension and extension != ".txt":
            raise SourceValidationError(
                "Direct text sources may only use a .txt filename."
            )

    return ValidatedSource(
        source_type=normalized_type,
        filename=filename.strip() if filename else None,
        mime_type=normalized_mime,
        file_size=len(content),
    )
