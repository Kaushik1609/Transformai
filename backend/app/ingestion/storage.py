"""Object-storage adapters for original ingestion files and generated artifacts.

Two adapters share the same storage-key contract:

  * ``LocalStorage`` — local/test development, offline execution, and the
    FakeLLMProvider workflows.
  * ``S3Storage`` — production S3-compatible object storage (AWS S3 or MinIO)
    driven entirely by environment configuration.

Selection is done by ``build_storage`` / ``get_storage`` from
``STORAGE_BACKEND``. There is deliberately NO fallback from ``s3`` to local
storage: a misconfigured S3 backend fails loudly instead of silently writing
to disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union
from uuid import UUID

from app.core.config import settings

try:  # botocore ships with boto3 (requirements.txt)
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - defensive; boto3 is a hard dependency
    ClientError = Exception  # type: ignore[assignment, misc]


def source_key(project_id: UUID, source_id: UUID, filename: str) -> str:
    """Return the approved relative key for an original source file."""
    safe_filename = Path(filename).name
    if not safe_filename or safe_filename in {".", ".."}:
        raise ValueError("A valid source filename is required.")
    return f"projects/{project_id}/sources/{source_id}/original{Path(safe_filename).suffix.lower()}"


class StorageConfigurationError(RuntimeError):
    """Raised when production object storage is misconfigured.

    Deliberately a ``RuntimeError`` (not ``ValueError`` / ``OSError``) so API
    handlers that map those to 4xx responses never swallow a production
    configuration failure as a not-found result.
    """


class LocalStorage:
    """Store original source bytes below the configured local root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def source_key(project_id: UUID, source_id: UUID, filename: str) -> str:
        """Return the approved relative key for an original source file."""
        return source_key(project_id, source_id, filename)

    def save(self, key: str, content: bytes, *, content_type: str | None = None) -> Path:
        """Write bytes to a key below the storage root and return its path.

        ``content_type`` is accepted for interface parity with ``S3Storage``;
        the local filesystem does not persist MIME metadata.
        """
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

    def delete(self, key: str) -> None:
        """Remove a stored artifact below the storage root for a given key.

        Keys that resolve outside the root raise ``ValueError``. A missing
        artifact is treated as an idempotent success so lifecycle cleanup can
        be retried safely. Unexpected filesystem errors propagate so cleanup
        failures are never silently swallowed.
        """
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage key escapes the configured storage root.")
        if path.is_dir():
            raise OSError(
                f"Storage key {key!r} resolves to a directory, not a stored artifact."
            )
        try:
            path.unlink()
        except FileNotFoundError:
            return


class S3Storage:
    """S3-compatible object-storage adapter (AWS S3 or MinIO).

    Implements the same key contract as ``LocalStorage`` so every artifact key
    (``projects/{project}/sources/{source}/original.ext`` and
    ``projects/{project}/jobs/{job}/outputs/{output}/result.ext``) round-trips
    to a real object store in production without re-keying.

    Credentials arrive exclusively from environment configuration; they are
    never logged, returned, or included in ``repr()``.
    """

    provider_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        path_style: bool = True,
        client: object | None = None,
    ) -> None:
        if not bucket:
            raise StorageConfigurationError(
                "S3Storage requires a bucket name (STORAGE_BUCKET)."
            )
        self._bucket = bucket
        self._region = region or "us-east-1"
        self._endpoint_url = endpoint_url or None
        self._path_style = bool(path_style)
        self._client = client
        if self._client is None:
            if not access_key or not secret_key:
                raise StorageConfigurationError(
                    "S3Storage requires STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY "
                    "when no client is injected."
                )
            import boto3
            from botocore.config import Config

            client_kwargs: dict = {
                "aws_access_key_id": access_key,
                "aws_secret_access_key": secret_key,
                "region_name": self._region,
                "config": Config(
                    s3={
                        "addressing_style": (
                            "path" if self._path_style else "auto"
                        )
                    },
                    retries={"max_attempts": 2},
                ),
            }
            if self._endpoint_url:
                client_kwargs["endpoint_url"] = self._endpoint_url
            self._client = boto3.client("s3", **client_kwargs)

    @staticmethod
    def source_key(project_id: UUID, source_id: UUID, filename: str) -> str:
        """Return the approved relative key for an original source file."""
        return source_key(project_id, source_id, filename)

    def save(self, key: str, content: bytes, *, content_type: str | None = None) -> str:
        """Upload bytes under a key and return the exact storage key used."""
        if not key:
            raise ValueError("A storage key is required.")
        try:
            self._client.put_object(  # type: ignore[union-attr]
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type or "application/octet-stream",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
                raise StorageConfigurationError(
                    f"S3 bucket {self._bucket!r} does not exist. Create it "
                    "before writing artifacts, or check STORAGE_BUCKET."
                ) from exc
            raise
        return key

    def read(self, key: str) -> bytes:
        """Read and return the bytes stored under a key."""
        if not key:
            raise ValueError("A storage key is required.")
        try:
            result = self._client.get_object(  # type: ignore[union-attr]
                Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "NotFound", "404"}:
                # Mirrors LocalStorage.read() -> FileNotFoundError (an OSError)
                # so existing callers keep their error handling.
                raise FileNotFoundError(key) from None
            if code == "NoSuchBucket":
                raise StorageConfigurationError(
                    f"S3 bucket {self._bucket!r} does not exist."
                ) from exc
            raise
        body = result.get("Body")
        if body is None:
            return b""
        return body.read()

    def delete(self, key: str) -> None:
        """Idempotently remove a stored object (missing keys are a no-op)."""
        if not key:
            raise ValueError("A storage key is required.")
        try:
            self._client.delete_object(  # type: ignore[union-attr]
                Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
                raise StorageConfigurationError(
                    f"S3 bucket {self._bucket!r} does not exist."
                ) from exc
            raise

    def __repr__(self) -> str:
        # Deliberately excludes access/secret keys.
        return (
            f"{type(self).__name__}(bucket={self._bucket!r}, "
            f"region={self._region!r}, endpoint={self._endpoint_url!r}, "
            f"path_style={self._path_style!r})"
        )


StorageAdapter = Union[LocalStorage, S3Storage]


def build_storage() -> StorageAdapter:
    """Build the configured object-storage adapter.

    Selection is driven by ``STORAGE_BACKEND``:

      * ``local`` — ``LocalStorage`` under ``STORAGE_LOCAL_PATH`` (tests,
        offline development, FakeLLMProvider workflows).
      * ``s3`` — ``S3Storage`` against AWS S3 or an S3-compatible endpoint
        (e.g. MinIO). Requires ``STORAGE_BUCKET``, ``STORAGE_ACCESS_KEY`` and
        ``STORAGE_SECRET_KEY``; ``STORAGE_REGION`` defaults to ``us-east-1``
        and ``STORAGE_ENDPOINT`` is optional (empty means AWS).

    There is deliberately NO fallback: selecting ``s3`` without a valid
    configuration raises ``StorageConfigurationError`` instead of silently
    writing to the local disk.
    """
    backend = settings.STORAGE_BACKEND
    if backend == "local":
        return LocalStorage(settings.STORAGE_LOCAL_PATH)
    if backend == "s3":
        missing = [
            name
            for name, value in (
                ("STORAGE_BUCKET", settings.STORAGE_BUCKET),
                ("STORAGE_ACCESS_KEY", settings.STORAGE_ACCESS_KEY),
                ("STORAGE_SECRET_KEY", settings.STORAGE_SECRET_KEY),
            )
            if not value
        ]
        if missing:
            raise StorageConfigurationError(
                "STORAGE_BACKEND=s3 requires " + ", ".join(missing) + "."
            )
        return S3Storage(
            bucket=settings.STORAGE_BUCKET,
            region=settings.STORAGE_REGION,
            endpoint_url=settings.STORAGE_ENDPOINT or None,
            access_key=settings.STORAGE_ACCESS_KEY,
            secret_key=settings.STORAGE_SECRET_KEY,
            path_style=settings.STORAGE_PATH_STYLE,
        )
    raise StorageConfigurationError(
        f"STORAGE_BACKEND={backend!r} is not supported (expected 'local' or 's3')."
    )


def get_storage() -> StorageAdapter:
    """Return a freshly-constructed configured storage adapter.

    Never memoized: tests monkeypatch ``settings.STORAGE_*`` per-test and the
    adapter must honor the current configuration at call time.
    """
    return build_storage()
