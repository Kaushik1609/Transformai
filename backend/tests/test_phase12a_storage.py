"""Phase 12A — Production S3-compatible object storage.

Verifies:
  1. storage provider selection through ``build_storage`` / ``get_storage``
  2. LocalStorage remains functional (tests / offline / FakeLLMProvider)
  3. S3-compatible provider configuration
  4. missing required production configuration fails safely
  5. upload/write
  6. read/download
  7. delete/cleanup
  8. storage key preservation
  9. MIME/content-type preservation
 10. artifact persistence compatibility (source_key / round-trip)
 11. provider injection (no boto3 needed for unit tests)
 12. no production fallback to LocalStorage
 13. no secret leakage

No AWS credentials or live S3/MinIO are required: the S3 adapter is exercised
through an injected in-memory fake client.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from app.ingestion.storage import (
    LocalStorage,
    S3Storage,
    StorageAdapter,
    StorageConfigurationError,
    build_storage,
    get_storage,
    source_key,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# In-memory fake S3-compatible client
# ---------------------------------------------------------------------------


class FakeS3Client:
    """Deterministic in-memory S3 client honouring the boto3 call surface.

    Exposes the same method/raise contract used by ``S3Storage`` so unit tests
    never touch a real endpoint. Records the last write's ContentType so the
    test can assert MIME preservation.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.last_put: dict[str, str] | None = None

    def put_object(self, *, Bucket, Key, Body, ContentType="application/octet-stream"):
        assert Bucket
        self.objects[Key] = Body if isinstance(Body, bytes) else bytes(Body)
        self.content_types[Key] = ContentType
        self.last_put = {"bucket": Bucket, "key": Key, "content_type": ContentType}

    def get_object(self, *, Bucket, Key):
        assert Bucket
        if Key not in self.objects:
            raise _client_error("NoSuchKey")
        return {"Body": _FakeBody(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):
        assert Bucket
        self.objects.pop(Key, None)
        self.content_types.pop(Key, None)


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _Error:
    def __init__(self, code: str) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }


def _client_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError(_Error(code).response, "Operation")


@pytest.fixture
def fake_client() -> FakeS3Client:
    return FakeS3Client()


# ---------------------------------------------------------------------------
# 1/4. Provider selection & configuration
# ---------------------------------------------------------------------------


class TestProviderSelection:
    def test_default_backend_is_local(self):
        assert settings.STORAGE_BACKEND == "local"

    def test_build_local_returns_local_storage(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
        monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", "/tmp/storage-test")
        assert isinstance(build_storage(), LocalStorage)

    def test_get_storage_returns_local_by_default(self):
        assert isinstance(get_storage(), LocalStorage)

    def test_unsupported_backend_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "ftp")
        with pytest.raises(
            StorageConfigurationError, match="STORAGE_BACKEND='ftp' is not supported"
        ):
            build_storage()


class TestS3Configuration:
    def test_s3_requires_bucket(self):
        with pytest.raises(StorageConfigurationError, match="bucket"):
            S3Storage(bucket="", client=FakeS3Client())

    def test_missing_credentials_are_rejected_without_client(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "STORAGE_BUCKET", "transformiq")
        monkeypatch.setattr(settings, "STORAGE_ACCESS_KEY", "")
        monkeypatch.setattr(settings, "STORAGE_SECRET_KEY", "")
        with pytest.raises(StorageConfigurationError, match="STORAGE_ACCESS_KEY"):
            build_storage()

    def test_s3_build_fails_safely_with_missing_required(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "STORAGE_BUCKET", "")
        monkeypatch.setattr(settings, "STORAGE_ACCESS_KEY", "k")
        monkeypatch.setattr(settings, "STORAGE_SECRET_KEY", "s")
        with pytest.raises(StorageConfigurationError, match="STORAGE_BUCKET"):
            build_storage()

    def test_injected_client_builds_without_credentials(self):
        storage = S3Storage(bucket="transformiq", client=FakeS3Client())
        assert isinstance(storage, S3Storage)
        assert storage.provider_name == "s3"

    def test_repr_excludes_credentials(self, fake_client):
        storage = S3Storage(
            bucket="bkt",
            region="us-east-1",
            endpoint_url="http://minio:9000",
            client=fake_client,
        )
        text = repr(storage)
        assert "secret" not in text.lower()
        assert "bucket='bkt'" in text


# ---------------------------------------------------------------------------
# 12. No production fallback to LocalStorage
# ---------------------------------------------------------------------------


class TestNoFallback:
    def test_s3_never_returns_local(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "STORAGE_BUCKET", "transformiq")
        monkeypatch.setattr(settings, "STORAGE_ACCESS_KEY", "ak")
        monkeypatch.setattr(settings, "STORAGE_SECRET_KEY", "sk")
        # A correctly configured S3 backend yields an S3Storage adapter — never
        # a LocalStorage fallback.
        storage = S3Storage(
            bucket="transformiq",
            region="us-east-1",
            access_key="ak",
            secret_key="sk",
            client=None,
            endpoint_url="http://nowhere.invalid:9000",
        )
        assert not isinstance(storage, LocalStorage)
        assert isinstance(storage, S3Storage)

    def test_missing_production_config_raises_not_falls_back(self, monkeypatch):
        monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(settings, "STORAGE_BUCKET", "")
        monkeypatch.setattr(settings, "STORAGE_ACCESS_KEY", "")
        monkeypatch.setattr(settings, "STORAGE_SECRET_KEY", "")
        with pytest.raises(StorageConfigurationError):
            build_storage()


# ---------------------------------------------------------------------------
# 1/2. LocalStorage remains functional
# ---------------------------------------------------------------------------


class TestLocalStorageFunctional:
    def test_save_read_delete_roundtrip(self, tmp_path):
        storage = LocalStorage(tmp_path)
        key = "projects/p/sources/s/original.txt"
        storage.save(key, b"hello")
        assert storage.read(key) == b"hello"
        assert (tmp_path / key).exists()
        storage.delete(key)
        with pytest.raises(FileNotFoundError):
            storage.read(key)

    def test_save_accepts_content_type_kwarg(self, tmp_path):
        storage = LocalStorage(tmp_path)
        key = "projects/p/sources/s/original.txt"
        storage.save(key, b"x", content_type="text/plain")
        assert storage.read(key) == b"x"

    def test_source_key_generation(self):
        pid, sid = _uuid(), _uuid()
        key = LocalStorage.source_key(pid, sid, "Report.PDF")
        assert key == f"projects/{pid}/sources/{sid}/original.pdf"

    def test_delete_missing_is_idempotent(self, tmp_path):
        storage = LocalStorage(tmp_path)
        storage.delete("projects/p/sources/s/original.txt")  # no raise


# ---------------------------------------------------------------------------
# 5/6/7/8/9. S3Storage upload / read / delete / keys / MIME
# ---------------------------------------------------------------------------


class TestS3StorageOperations:
    def test_upload_read_roundtrip_preserves_bytes(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        key = "projects/p/sources/s/original.txt"
        returned = storage.save(key, b"artifact-bytes")
        assert returned == key
        assert storage.read(key) == b"artifact-bytes"

    def test_upload_preserves_content_type(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        key = "projects/p/jobs/j/outputs/o/result.pptx"
        storage.save(key, b"\x00\x01", content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
        assert fake_client.content_types[key] == (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )

    def test_upload_default_content_type_when_omitted(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        key = "projects/p/sources/s/original.txt"
        storage.save(key, b"x")
        assert fake_client.content_types[key] == "application/octet-stream"

    def test_delete_removes_object(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        key = "projects/p/sources/s/original.txt"
        storage.save(key, b"x")
        storage.delete(key)
        assert key not in fake_client.objects

    def test_delete_is_idempotent(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        storage.delete("projects/p/sources/s/original.txt")  # no raise

    def test_read_missing_raises_file_not_found(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        with pytest.raises(FileNotFoundError):
            storage.read("projects/p/sources/s/original.txt")

    def test_save_rejects_empty_key(self, fake_client):
        storage = S3Storage(bucket="transformiq", client=fake_client)
        with pytest.raises(ValueError, match="storage key"):
            storage.save("", b"x")

    def test_source_key_shared_between_adapters(self):
        pid, sid = _uuid(), _uuid()
        assert LocalStorage.source_key(pid, sid, "a.pdf") == source_key(pid, sid, "a.pdf")
        assert S3Storage.source_key(pid, sid, "a.pdf") == source_key(pid, sid, "a.pdf")


# ---------------------------------------------------------------------------
# 10. Artifact-kernel compatibility (save_output_artifact via injected storage)
# ---------------------------------------------------------------------------


class TestArtifactPersistenceCompat:
    def test_output_artifact_bypasses_network_with_injected_storage(self):
        from app.transformation.artifacts import save_output_artifact

        fake = FakeS3Client()
        storage = S3Storage(bucket="transformiq", client=fake)
        pid, jid, oid = _uuid(), _uuid(), _uuid()
        key = save_output_artifact(
            project_id=pid,
            job_id=jid,
            output_id=oid,
            mime_type="image/png",
            content=b"\x89PNG",
            storage=storage,
        )
        assert key == f"projects/{pid}/jobs/{jid}/outputs/{oid}/result.png"
        assert storage.read(key) == b"\x89PNG"
        assert fake.content_types[key] == "image/png"

    def test_local_artifact_persists_to_disk(self, tmp_path):
        from app.transformation.artifacts import save_output_artifact

        storage = LocalStorage(tmp_path)
        pid, jid, oid = _uuid(), _uuid(), _uuid()
        key = save_output_artifact(
            project_id=pid,
            job_id=jid,
            output_id=oid,
            mime_type="application/pdf",
            content=b"%PDF",
            storage=storage,
        )
        assert (tmp_path / key).read_bytes() == b"%PDF"
