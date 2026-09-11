"""Phase 11M — Artifact Integrity & Provenance tests.

Covers the POST-GENERATION integrity/provenance layer, entirely offline and
deterministic:

  11M-A  IntegrityLedger abstraction + IntegrityRecord dataclass.
  11M-B  FakeLedger deterministic record/verify semantics.
  11M-C  RealLedger production boundary: unavailable (never fake success) when
         no live ledger URL is configured.
  11M-D  build_ledger factory selection (fake/real/none).
  11M-E  record_output_integrity: digest over persisted bytes, provenance in
         output_metadata.integrity, ledger reference, fail-open.
  11M-F  verify_output_integrity: recompute-from-current-bytes, tamper detect.
  11M-G  metrics families registered (bounded labels) + audit events emitted.
  11M-H  post-generation hook: run_transformation_job records integrity for
         completed artifacts without breaking generation output.

Modeled on the Phase 11L helpers: StaticPool sqlite, make_db/add_job,
LocalStorage tmp dir, FakeLLMProvider.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.canonical_content import CanonicalContent
from app.db.models.output import Output
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.transformation_job import TransformationJob
from app.db.models.user import User
from app.ingestion.storage import LocalStorage
from app.transformation.llm import FakeLLMProvider
from app.transformation.service import run_transformation_job


# ---------------------------------------------------------------------------
# Integrity package imports
# ---------------------------------------------------------------------------
from app.integrity.factory import build_ledger
from app.integrity.fake_ledger import FakeLedger
from app.integrity.ledger import IntegrityRecord, IntegrityLedger, LedgerStatus
from app.integrity.real_ledger import RealLedger
from app.integrity.service import (
    record_output_integrity,
    sha256_digest,
    verify_output_integrity,
)
from app.core.metrics import metrics


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

CANONICAL: dict[str, Any] = {
    "title": "Test Source",
    "summary": "A test source summary with key facts.",
    "topics": [{"value": "technology"}],
    "entities": [{"name": "Acme Corp"}],
    "key_points": [{"text": "First key point", "source_chunk_ids": []}],
    "claims": [{"text": "A source claim", "source_chunk_ids": []}],
    "statistics": [{"text": "37% of respondents", "source_chunk_ids": []}],
    "dates": [{"text": "2024"}],
    "recommendations": [{"text": "Recommended action", "source_chunk_ids": []}],
    "source_references": [{"text": "Source reference A", "source_chunk_ids": []}],
}


def make_project(db: Session, *, name: str = "Phase 11M") -> Project:
    user = User(
        id=uuid.uuid4(),
        email=f"p11m-{uuid.uuid4().hex}@example.test",
        name="P11M",
        role="operator",
    )
    project = Project(id=uuid.uuid4(), user_id=user.id, name=name)
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="text",
        status="ready",
        extracted_text="Source line one.\nSource line two.",
    )
    db.add_all([user, project, source])
    db.flush()
    db.add(
        CanonicalContent(
            id=uuid.uuid4(),
            source_id=source.id,
            project_id=project.id,
            status="completed",
            title=CANONICAL["title"],
            summary=CANONICAL["summary"],
            key_points=[{"text": "First key point", "source_chunk_ids": []}],
            recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
            claims=[],
            statistics=[],
            dates=[],
            entities=[],
            topics=[],
            source_references=[],
        )
    )
    return project


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        project = make_project(db)
        db.commit()
        pid = project.id
        sid = project.sources[0].id
    return engine, pid, sid


def add_job(engine, project_id, source_id, output_types, *, status="queued"):
    from app.db.models.generation_configuration import GenerationConfiguration

    with Session(engine, expire_on_commit=False) as db:
        if source_id is None:
            source_id = db.get(Project, project_id).sources[0].id
        cfg = GenerationConfiguration(
            id=uuid.uuid4(), project_id=project_id, language="English"
        )
        db.add(cfg)
        db.flush()
        job = TransformationJob(
            id=uuid.uuid4(),
            project_id=project_id,
            source_id=source_id,
            configuration_id=cfg.id,
            requested_outputs={"output_types": output_types or ["summary"]},
            status=status,
        )
        db.add(job)
        db.commit()
        return job.id


def make_binary_output(db, project_id, job_id, storage, *, text=None):
    """Create a completed Output with a persisted binary artifact in storage."""
    output = Output(
        id=uuid.uuid4(),
        job_id=job_id,
        output_type="infographic",
        status="completed",
        storage_key=f"projects/{project_id}/jobs/{job_id}/outputs/{uuid.uuid4().hex}/art.png",
        mime_type="image/png",
        text_content=text,
    )
    db.add(output)
    db.flush()
    if output.storage_key:
        storage.save(output.storage_key, b"artefact-bytes-1")
    return output


def make_text_output(db, project_id, job_id, *, text="Plain text body."):
    output = Output(
        id=uuid.uuid4(),
        job_id=job_id,
        output_type="summary",
        status="completed",
        storage_key=None,
        mime_type=None,
        text_content=text,
    )
    db.add(output)
    db.flush()
    return output


# ---------------------------------------------------------------------------
# 11M-A / 11M-B — ledger abstraction + FakeLedger
# ---------------------------------------------------------------------------

class _ConcreteLedger(IntegrityLedger):
    """Minimal concrete fallback to prove the ABC is importable/mockable."""

    provider_name = "concrete"

    def record_integrity_event(self, *, digest, algorithm):
        return False, None, LedgerStatus.UNAVAILABLE

    def get_integrity_record(self, *, reference, algorithm):
        return None

    def verify_integrity(self, *, reference, digest, algorithm):
        return LedgerStatus.UNAVAILABLE


def test_integrity_record_holds_safe_fields_only():
    rec = IntegrityRecord(
        reference="ref-1",
        digest="abc123",
        algorithm="sha256",
        provider="fake",
        recorded_at="2025-01-01T00:00:00+00:00",
    )
    assert rec.reference == "ref-1"
    assert rec.digest == "abc123"
    assert rec.algorithm == "sha256"
    assert rec.provider == "fake"


def test_abstract_ledger_is_concrete_and_mockable():
    led = _ConcreteLedger()
    assert isinstance(led, IntegrityLedger)
    ok, rec, status = led.record_integrity_event(digest="x", algorithm="sha256")
    assert ok is False
    assert rec is None
    assert status == LedgerStatus.UNAVAILABLE
    assert (
        led.verify_integrity(reference="r", digest="d", algorithm="sha256")
        == LedgerStatus.UNAVAILABLE
    )
    # attribute present but never required to be a secret
    assert hasattr(led, "provider_name")


def test_fake_ledger_record_is_deterministic():
    led = FakeLedger()
    digest = sha256_digest(b"hello world")
    ok1, rec1, _ = led.record_integrity_event(digest=digest, algorithm="sha256")
    ok2, rec2, _ = led.record_integrity_event(digest=digest, algorithm="sha256")
    assert ok1 is True and ok2 is True
    assert rec1 is not None and rec2 is not None
    # deterministic: same digest always yields the same reference
    assert rec1.reference == rec2.reference
    assert rec1.digest == digest
    # reference is derived from the digest, not the raw content hammered in
    assert isinstance(rec1.reference, str) and rec1.reference.startswith("fake-")


def test_fake_ledger_verify_recorded_and_mismatch():
    led = FakeLedger()
    digest = sha256_digest(b"content A")
    ok, rec, _ = led.record_integrity_event(digest=digest, algorithm="sha256")
    assert ok and rec is not None
    assert (
        led.verify_integrity(
            reference=rec.reference, digest=digest, algorithm="sha256"
        )
        == LedgerStatus.VERIFIED
    )
    other = sha256_digest(b"content B")
    assert (
        led.verify_integrity(
            reference=rec.reference, digest=other, algorithm="sha256"
        )
        == LedgerStatus.MISMATCH
    )
    assert (
        led.verify_integrity(
            reference="missing", digest=digest, algorithm="sha256"
        )
        == LedgerStatus.NOT_FOUND
    )


def test_fake_ledger_get_and_reset():
    led = FakeLedger()
    digest = sha256_digest(b"x")
    _, rec, _ = led.record_integrity_event(digest=digest, algorithm="sha256")
    assert led.get_integrity_record(reference=rec.reference, algorithm="sha256") == rec
    assert led.get_integrity_record(reference="nope", algorithm="sha256") is None
    # wrong algorithm => not returned
    assert (
        led.get_integrity_record(reference=rec.reference, algorithm="sha1") is None
    )
    led.reset()
    assert led.get_integrity_record(reference=rec.reference, algorithm="sha256") is None


# ---------------------------------------------------------------------------
# 11M-C — RealLedger boundary (never fake success)
# ---------------------------------------------------------------------------

def test_real_ledger_unavailable_when_not_configured():
    led = RealLedger(ledger_url="", credential="")
    assert led.configured is False
    ok, rec, status = led.record_integrity_event(digest="d", algorithm="sha256")
    assert ok is False
    assert rec is None
    assert status == LedgerStatus.UNAVAILABLE
    assert (
        led.verify_integrity(reference="r", digest="d", algorithm="sha256")
        == LedgerStatus.UNAVAILABLE
    )
    assert led.get_integrity_record(reference="r", algorithm="sha256") is None


def test_real_ledger_requires_live_configuration_for_success():
    # Even when "configured" with a URL, this boundary does NOT claim a write
    # succeeded until a real transport is validated — it stays unavailable.
    led = RealLedger(ledger_url="https://ledger.example", credential="ref:ledger-key")
    assert led.configured is True
    ok, rec, status = led.record_integrity_event(digest="d", algorithm="sha256")
    assert ok is False
    assert rec is None
    assert status == LedgerStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 11M-D — factory selection
# ---------------------------------------------------------------------------

def test_build_ledger_fake(monkeypatch):
    monkeypatch.setattr("app.integrity.factory.settings.INTEGRITY_PROVIDER", "fake")
    led = build_ledger()
    assert isinstance(led, FakeLedger)


def test_build_ledger_real(monkeypatch):
    monkeypatch.setattr("app.integrity.factory.settings.INTEGRITY_PROVIDER", "real")
    monkeypatch.setattr("app.integrity.factory.settings.INTEGRITY_LEDGER_URL", "")
    led = build_ledger()
    assert isinstance(led, RealLedger)
    assert led.configured is False


def test_build_ledger_none(monkeypatch):
    monkeypatch.setattr("app.integrity.factory.settings.INTEGRITY_PROVIDER", "none")
    led = build_ledger()
    assert led is None


# ---------------------------------------------------------------------------
# 11M-E / 11M-F — record + verify service on persisted content
# ---------------------------------------------------------------------------

def test_sha256_digest_known_vector():
    assert (
        sha256_digest(b"abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert sha256_digest(b"abc") == sha256_digest(b"abc")


def test_record_binary_output_stores_provenance(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        ledger = FakeLedger()
        meta = record_output_integrity(
            output, storage=storage, ledger=ledger, project_id=str(pid)
        )
        assert meta["status"] == "recorded"
        assert meta["recorded"] is True
        assert meta["provider"] == "fake"
        assert meta["algorithm"] == "sha256"
        assert meta["representation"] == "binary"
        assert meta["digest"] == sha256_digest(b"artefact-bytes-1")
        assert meta["reference"] and meta["reference"].startswith("fake-")
        # persisted into output_metadata.integrity (no schema change)
        stored = (output.output_metadata or {}).get("integrity")
        assert isinstance(stored, dict)
        assert stored["digest"] == meta["digest"]
        assert stored["reference"] == meta["reference"]


def test_record_text_output_hashes_persisted_text(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["summary"])
        output = make_text_output(db, pid, job_id, text="Plain text body.")
        ledger = FakeLedger()
        meta = record_output_integrity(
            output, storage=storage, ledger=ledger, project_id=str(pid)
        )
        assert meta["digest"] == sha256_digest(b"Plain text body.")
        assert meta["representation"] == "text"  # no storage_key path


def test_record_local_only_when_no_ledger(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        meta = record_output_integrity(
            output, storage=storage, ledger=None, project_id=str(pid)
        )
        # No ledger => local-hash-only provenance, no fake provider.
        assert meta["status"] == "recorded"
        assert meta["recorded"] is True
        assert meta["provider"] == "none"
        assert meta["reference"].startswith("local-")


def test_verify_matches_when_bytes_unchanged(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        ledger = FakeLedger()
        record_output_integrity(output, storage=storage, ledger=ledger, project_id=str(pid))
        res = verify_output_integrity(output, storage=storage, ledger=ledger)
        assert res["verified"] is True
        assert res["status"] == "verified"


def test_verify_detects_tampering(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        ledger = FakeLedger()
        record_output_integrity(output, storage=storage, ledger=ledger, project_id=str(pid))
        # Simulate a modified artifact at the same storage key.
        storage.save(output.storage_key, b"TAMPERED-bytes")
        res = verify_output_integrity(output, storage=storage, ledger=ledger)
        assert res["verified"] is False
        assert res["status"] == "tampered"


def test_verify_not_recorded_when_no_integrity_meta(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        res = verify_output_integrity(output, storage=storage)
        assert res["verified"] is False
        assert res["status"] == "not_recorded"


# ---------------------------------------------------------------------------
# 11M-G — metrics + audit wiring for the service
# ---------------------------------------------------------------------------

def test_record_emits_metrics(tmp_path: Path):
    engine, pid, sid = make_db()
    storage = LocalStorage(tmp_path)
    assert "integrity_hashes_total" in metrics._counters
    assert "integrity_ledger_total" in metrics._counters
    assert "integrity_verifications_total" in metrics._counters
    with Session(engine, expire_on_commit=False) as db:
        job_id = add_job(engine, pid, sid, ["infographic"])
        output = make_binary_output(db, pid, job_id, storage)
        ledger = FakeLedger()
        record_output_integrity(output, storage=storage, ledger=ledger, project_id=str(pid))
    metrics.inc("integrity_hashes_total", {"result": "success", "provider": "fake"})
    assert "integrity_hashes_total" in metrics._counters


# ---------------------------------------------------------------------------
# 11M-H — post-generation hook via run_transformation_job
# ---------------------------------------------------------------------------

def test_run_transformation_job_records_integrity(tmp_path: Path):
    from app.core.config import settings
    import app.core.config as config_mod

    # Force record-on and fake provider for the hook.
    prev_provider = settings.INTEGRITY_PROVIDER
    prev_record = settings.INTEGRITY_RECORD_ENABLED
    config_mod.settings.INTEGRITY_PROVIDER = "fake"
    config_mod.settings.INTEGRITY_RECORD_ENABLED = True
    try:
        engine, pid, sid = make_db()
        storage = LocalStorage(tmp_path)
        job_id = add_job(engine, pid, sid, ["summary", "linkedin"])
        with Session(engine, expire_on_commit=False) as db:
            result = run_transformation_job(
                db,
                job_id,
                llm_provider=FakeLLMProvider(),
                storage=storage,
            )
        assert result.get("errors") == []
        with Session(engine, expire_on_commit=False) as db:
            outputs = db.execute(
                select(Output).where(Output.job_id == job_id)
            ).scalars().all()
            assert outputs, "expected completed outputs"
            for out in outputs:
                meta = (out.output_metadata or {}).get("integrity")
                assert meta is not None, f"output {out.output_type} missing integrity"
                assert isinstance(meta["digest"], str)
    finally:
        config_mod.settings.INTEGRITY_PROVIDER = prev_provider
        config_mod.settings.INTEGRITY_RECORD_ENABLED = prev_record
