"""PDF and DOCX text extraction for synchronous Phase 3C ingestion."""

from __future__ import annotations

from io import BytesIO

import fitz
from docx import Document


class DocumentExtractionError(ValueError):
    """Raised when a PDF or DOCX cannot be read as a text document."""


def extract_pdf(content: bytes) -> str:
    """Extract text from all PDF pages in document order."""
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            return "\n".join(
                page.get_text("text")
                for page in document
                if page.get_text("text").strip()
            )
    except Exception as exc:
        raise DocumentExtractionError("Could not read the PDF document.") from exc


def extract_docx(content: bytes) -> str:
    """Extract non-empty DOCX paragraphs in document order."""
    try:
        document = Document(BytesIO(content))
        return "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        )
    except Exception as exc:
        raise DocumentExtractionError("Could not read the DOCX document.") from exc
