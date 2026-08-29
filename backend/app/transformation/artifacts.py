"""Persistence of generated output artifacts (PPTX, PNG, PDF) to storage.

Follows the approved storage-key structure from docs/API_DATABASE_DESIGN.md:
    projects/{project_id}/jobs/{job_id}/outputs/{output_id}/result.ext

Only binary artifacts (presentation PPTX and infographic PNG/PDF) are written
to object storage; all text/structured outputs are persisted in the `outputs`
table directly.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.ingestion.storage import LocalStorage
from app.transformation.render.pptx import PPTX_MIME_TYPE

_MIME_EXT: dict[str, str] = {
    PPTX_MIME_TYPE: ".pptx",
    "application/pdf": ".pdf",
    "image/png": ".png",
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ): ".docx",
    "text/plain": ".txt",
}


def ext_for_mime(mime_type: str) -> str:
    """Return a safe file extension for a MIME type."""
    return _MIME_EXT.get(mime_type, ".bin")


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


def get_storage() -> LocalStorage:
    """Build the configured storage adapter (local by default)."""
    return LocalStorage(settings.STORAGE_LOCAL_PATH)


def save_output_artifact(
    *,
    project_id: UUID,
    job_id: UUID,
    output_id: UUID,
    mime_type: str,
    content: bytes,
    storage: LocalStorage | None = None,
) -> str:
    """Persist an output artifact and return its storage key."""
    storage = storage or get_storage()
    key = output_storage_key(project_id, job_id, output_id, mime_type)
    storage.save(key, content)
    return key


def storage_root(storage: LocalStorage | None = None) -> Path:
    """Return the storage root path (handy for tests)."""
    storage = storage or get_storage()
    return storage.root
