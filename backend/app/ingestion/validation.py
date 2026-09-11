"""Validation primitives for supported Phase 3 source inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

SUPPORTED_SOURCE_TYPES = frozenset({"text", "txt", "pdf", "docx"})

MIME_TYPES_BY_SOURCE_TYPE = {
    "text": frozenset({"text/plain", "text/x-plain", "application/octet-stream"}),
    "txt": frozenset({"text/plain", "text/x-plain", "application/octet-stream"}),
    "pdf": frozenset(
        {
            "application/pdf",
            "application/x-pdf",
            "application/acrobat",
            "applications/vnd.pdf",
            "text/pdf",
            "application/octet-stream",
        }
    ),
    "docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "application/docx",
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
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


_PDF_MAGIC = b"%PDF-"
# ZIP local-file header (empty/zero-file marker) covers valid .docx containers.
_DOCX_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def _matches_docx_magic(content: bytes) -> bool:
    return any(content.startswith(magic) for magic in _DOCX_MAGIC)


def _detected_document_signature(content: bytes) -> str | None:
    """Return 'pdf' or 'docx' when the bytes start with a known signature."""
    if content.startswith(_PDF_MAGIC):
        return "pdf"
    if _matches_docx_magic(content):
        return "docx"
    return None


def _validate_magic_bytes(*, source_type: str, content: bytes) -> None:
    """Reject files whose content is a *known different* document type.

    Guards against type-confusion uploads (a real PDF renamed to .docx or .txt,
    a ZIP/DOCX container uploaded as a PDF). Content with no known signature is
    left to extraction, which produces the standard controlled parsing error —
    this preserves the existing 'could not read the document' contract for
    arbitrary/corrupt bytes while still rejecting mislabeled valid documents.
    """
    detected = _detected_document_signature(content)
    if source_type in {"pdf", "docx"}:
        if detected is not None and detected != source_type:
            raise SourceValidationError(
                f"{source_type.upper()} content does not match its declared type "
                f"(detected {detected.upper()} signature)."
            )
    elif detected is not None:
        raise SourceValidationError(
            "Text content appears to be a binary document (PDF/DOCX); "
            "use the document upload endpoint instead."
        )


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

    _validate_magic_bytes(source_type=normalized_type, content=content)

    normalized_mime = (mime_type or "").split(";")[0].strip().lower()
    allowed_mimes = MIME_TYPES_BY_SOURCE_TYPE[normalized_type]
    if not normalized_mime:
        normalized_mime = next(iter(allowed_mimes))
    elif normalized_mime not in allowed_mimes:
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
