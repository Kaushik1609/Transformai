"""Persistence and resolution of generated output artifacts to storage.

Follows the approved storage-key structure from docs/API_DATABASE_DESIGN.md:
    projects/{project_id}/jobs/{job_id}/outputs/{output_id}/result.ext

Binary artifacts (presentation PPTX, infographic PNG + PDF companion, and the
video-package PDF + SRT companion) are written to object storage; all
text/structured outputs are persisted in the `outputs` table directly.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

from app.core.metrics import metrics
from app.db.models.output import Output
from app.ingestion.storage import StorageAdapter, get_storage as get_configured_storage
from app.transformation.render.pptx import PPTX_MIME_TYPE

_MIME_EXT: dict[str, str] = {
    PPTX_MIME_TYPE: ".pptx",
    "application/pdf": ".pdf",
    "application/x-subrip": ".srt",
    "image/png": ".png",
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ): ".docx",
    "text/plain": ".txt",
}


def ext_for_mime(mime_type: str) -> str:
    """Return a safe file extension for a MIME type."""
    return _MIME_EXT.get(mime_type, ".bin")


def sha256_hex(content: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of artifact bytes.

    Used to record artifact integrity in ``output_metadata`` (no database
    schema change).  Deterministic and offline.
    """
    return hashlib.sha256(content).hexdigest()


def output_storage_key(
    project_id: UUID,
    job_id: UUID,
    output_id: UUID,
    mime_type: str,
) -> str:
    """Return the approved relative storage key for an output artifact."""
    return (
        f"projects/{project_id}/jobs/{job_id}/outputs/{output_id}/result"
        f"{ext_for_mime(mime_type)}"
    )


def get_storage() -> StorageAdapter:
    """Build the configured storage adapter (local default; S3-compatible in production)."""
    return get_configured_storage()


def save_output_artifact(
    *,
    project_id: UUID,
    job_id: UUID,
    output_id: UUID,
    mime_type: str,
    content: bytes,
    storage: StorageAdapter | None = None,
) -> str:
    """Persist an output artifact and return its storage key."""
    storage = storage or get_storage()
    key = output_storage_key(project_id, job_id, output_id, mime_type)
    started = time.monotonic()
    try:
        storage.save(key, content, content_type=mime_type)
    except Exception:
        metrics.inc("artifacts_failed_total")
        raise
    metrics.inc("artifacts_saved_total")
    metrics.inc("artifacts_saved_bytes_total", amount=len(content))
    metrics.observe(
        "artifact_save_duration_seconds", time.monotonic() - started
    )
    return key


def storage_root(storage: StorageAdapter | None = None) -> Path:
    """Return the local storage root path (only meaningful for ``LocalStorage``)."""
    storage = storage or get_storage()
    root = getattr(storage, "root", None)
    if root is None:
        raise RuntimeError("storage_root() requires a local storage backend.")
    return root


class ArtifactFile(NamedTuple):
    """Resolved artifact download info: storage key, safe filename, MIME type."""

    storage_key: str
    filename: str
    mime_type: str


_COMPANION_KEYS: dict[str, str] = {
    "pdf": "pdf_storage_key",
    "srt": "subtitle_storage_key",
}
_COMPANION_FILENAMES: dict[str, str] = {
    "pdf": "{stem}.pdf",
    "srt": "{stem}_subtitles.srt",
}
_PDF_MIME_TYPE = "application/pdf"
_SRT_MIME_TYPE = "application/x-subrip"


def _safe_filename_stem(value: str) -> str:
    """Return a header-safe filename stem derived from a known output type."""
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", value or "output")
    return stem or "output"


def artifact_file(output: Output, role: str) -> ArtifactFile | None:
    """Resolve an artifact role to (storage key, safe filename, MIME type).

    Keys are derived exclusively from the authorized ``Output`` record and its
    ``output_metadata`` — never from client-supplied paths or storage keys.
    Returns ``None`` when the requested artifact is not available (missing
    storage key / MIME type / companion metadata, or an unsupported role).
    """
    stem = _safe_filename_stem(output.output_type)
    if role == "primary":
        if not output.storage_key or not output.mime_type:
            return None
        return ArtifactFile(
            storage_key=output.storage_key,
            filename=f"{stem}{ext_for_mime(output.mime_type)}",
            mime_type=output.mime_type,
        )
    metadata_key = _COMPANION_KEYS.get(role)
    if metadata_key is None:
        return None
    storage_key = (output.output_metadata or {}).get(metadata_key)
    if not storage_key:
        return None
    if role == "pdf":
        mime_type = _PDF_MIME_TYPE
    else:  # "srt"
        mime_type = _SRT_MIME_TYPE
    return ArtifactFile(
        storage_key=storage_key,
        filename=_COMPANION_FILENAMES[role].format(stem=stem),
        mime_type=mime_type,
    )
