"""Phase 3A tests for validation, storage, normalization, and chunking."""

import uuid

import pytest

from app.ingestion.storage import LocalStorage
from app.ingestion.text import chunk_text, normalize_text
from app.ingestion.validation import SourceValidationError, validate_source


class TestSourceValidation:
    def test_accepts_direct_text(self):
        result = validate_source(
            source_type="text",
            content=b"hello",
            max_size_bytes=10,
        )
        assert result.source_type == "text"
        assert result.file_size == 5

    @pytest.mark.parametrize(
        ("source_type", "filename", "mime_type"),
        [
            ("txt", "notes.txt", "text/plain"),
            ("pdf", "report.pdf", "application/pdf"),
            (
                "docx",
                "report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ],
    )
    def test_accepts_supported_file_types(self, source_type, filename, mime_type):
        result = validate_source(
            source_type=source_type,
            content=b"content",
            filename=filename,
            mime_type=mime_type,
            max_size_bytes=100,
        )
        assert result.source_type == source_type
        assert result.filename == filename

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"source_type": "image", "content": b"x"},
            {"source_type": "pdf", "content": b"x", "filename": "report.pdf", "mime_type": "text/plain"},
            {"source_type": "pdf", "content": b"x", "filename": "report.txt", "mime_type": "application/pdf"},
            {"source_type": "pdf", "content": b"", "filename": "report.pdf", "mime_type": "application/pdf"},
        ],
    )
    def test_rejects_invalid_sources(self, kwargs):
        with pytest.raises(SourceValidationError):
            validate_source(max_size_bytes=100, **kwargs)

    def test_rejects_oversized_content(self):
        with pytest.raises(SourceValidationError, match="maximum size"):
            validate_source(source_type="text", content=b"12345", max_size_bytes=4)


class TestLocalStorage:
    def test_source_key_uses_approved_layout_and_safe_filename(self):
        key = LocalStorage.source_key(
            uuid.UUID("11111111-1111-4111-8111-111111111111"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"),
            "../report.PDF",
        )
        assert key == (
            "projects/11111111-1111-4111-8111-111111111111/"
            "sources/22222222-2222-4222-8222-222222222222/original.pdf"
        )

    def test_round_trips_original_bytes(self, tmp_path):
        storage = LocalStorage(tmp_path)
        key = "projects/project/sources/source/original.txt"
        content = b"original bytes"
        storage.save(key, content)
        assert storage.read(key) == content

    def test_rejects_path_escape(self, tmp_path):
        storage = LocalStorage(tmp_path)
        with pytest.raises(ValueError):
            storage.save("../../outside.txt", b"blocked")


class TestTextUtilities:
    def test_normalizes_line_endings_whitespace_and_blank_lines(self):
        assert normalize_text("  First\r\n\r\n\r\n  Second  ") == "First\n\nSecond"

    def test_chunks_are_ordered_and_overlap(self):
        chunks = chunk_text("abcdefghij", chunk_size=6, overlap=2)
        assert chunks == ["abcdef", "efghij"]

    def test_empty_text_has_no_chunks(self):
        assert chunk_text(" \n\t") == []

    @pytest.mark.parametrize(
        ("chunk_size", "overlap"),
        [(0, 0), (4, 4), (4, -1)],
    )
    def test_rejects_invalid_chunk_parameters(self, chunk_size, overlap):
        with pytest.raises(ValueError):
            chunk_text("content", chunk_size=chunk_size, overlap=overlap)
