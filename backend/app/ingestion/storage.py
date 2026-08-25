"""Local storage adapter for original ingestion files."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID


class LocalStorage:
    """Store original source bytes below the configured local root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def source_key(project_id: UUID, source_id: UUID, filename: str) -> str:
        """Return the approved relative key for an original source file."""
        safe_filename = Path(filename).name
        if not safe_filename or safe_filename in {".", ".."}:
            raise ValueError("A valid source filename is required.")
        return f"projects/{project_id}/sources/{source_id}/original{Path(safe_filename).suffix.lower()}"

    def save(self, key: str, content: bytes) -> Path:
        """Write bytes to a key below the storage root and return its path."""
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("Storage key escapes the configured storage root.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def read(self, key: str) -> bytes:
        """Read bytes from a key below the storage root."""
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage key escapes the configured storage root.")
        return path.read_bytes()
