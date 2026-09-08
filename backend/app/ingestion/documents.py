"""PDF and DOCX text extraction for synchronous Phase 3C ingestion.

Phase 13E adds bounded processing budgets so a single source file can never
exhaust worker time or memory: PDFs are capped by page count and extracted
characters; DOCX files are capped by extracted characters. A document
exceeding a cap raises ``DocumentExtractionError`` (a controlled ingestion
failure) — it is never silently truncated.
"""
from __future__ import annotations

from io import BytesIO

import fitz
from docx import Document

from app.core.config import settings


class DocumentExtractionError(ValueError):
    """Raised when a PDF or DOCX cannot be read as a text document."""


def _char_budget() -> int:
    return settings.MAX_EXTRACTED_CHARS


def extract_pdf(content: bytes) -> str:
    """Extract text from PDF pages in document order (bounded by page/char caps)."""
    max_pages = settings.MAX_PDF_PAGES
    max_chars = _char_budget()
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            if document.needs_pass or document.is_encrypted:
                raise DocumentExtractionError(
                    "PDF document is password-protected/encrypted."
                )
            if document.page_count > max_pages:
                raise DocumentExtractionError(
                    f"PDF page count ({document.page_count}) exceeds the "
                    f"configured limit of {max_pages} pages."
                )
            pages: list[str] = []
            total = 0
            for page in document:
                text = page.get_text("text")
                if not text.strip():
                    continue
                total += len(text)
                if total > max_chars:
                    raise DocumentExtractionError(
                        "PDF text exceeds the configured extraction limit "
                        f"of {max_chars} characters."
                    )
                pages.append(text)
            return "\n".join(pages)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("Could not read the PDF document.") from exc


def extract_docx(content: bytes) -> str:
    """Extract non-empty DOCX paragraphs in document order (bounded char cap)."""
    max_chars = _char_budget()
    try:
        document = Document(BytesIO(content))
        paragraphs: list[str] = []
        total = 0
        for paragraph in document.paragraphs:
            text = paragraph.text
            if not text.strip():
                continue
            total += len(text)
            if total > max_chars:
                raise DocumentExtractionError(
                    "DOCX text exceeds the configured extraction limit "
                    f"of {max_chars} characters."
                )
            paragraphs.append(text)
        return "\n".join(paragraphs)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("Could not read the DOCX document.") from exc