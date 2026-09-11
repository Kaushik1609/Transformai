"""Phase 11M — deterministic in-memory FakeLedger.

Used for unit tests, local development and offline execution. It requires no
network, wallet, blockchain node, API key or credentials, and it is fully
deterministic: the same digest+algorithm always yields the same reference
(``fake-<digest>``), so the complete integrity lifecycle can be exercised and
asserted in tests.

IMPORTANT: FakeLedger is local/test-only. See ``RealLedger`` (real_ledger.py)
for the production boundary.
"""

from __future__ import annotations

import hashlib

from app.integrity.ledger import IntegrityLedger, IntegrityRecord, LedgerStatus


class FakeLedger(IntegrityLedger):
    """Deterministic, offline, in-memory provenance ledger."""

    provider_name = "fake"

    def __init__(self) -> None:
        # reference -> IntegrityRecord
        self._records: dict[str, IntegrityRecord] = {}

    @staticmethod
    def _reference_for(digest: str) -> str:
        """Derive a stable, deterministic reference from the digest.

        Using the digest itself would make the reference length unbounded for
        arbitrary digests; we normalize through a fixed-width hash so the
        reference is always a safe, bounded identifier.
        """
        return "fake-" + hashlib.sha256(digest.encode("utf-8")).hexdigest()

    def record_integrity_event(
        self,
        *,
        digest: str,
        algorithm: str,
    ) -> tuple[bool, IntegrityRecord | None, LedgerStatus]:
        reference = self._reference_for(digest)
        record = IntegrityRecord(
            reference=reference,
            digest=digest,
            algorithm=algorithm,
            provider=self.provider_name,
        )
        self._records[reference] = record
        return True, record, LedgerStatus.RECORDED

    def get_integrity_record(
        self,
        *,
        reference: str,
        algorithm: str,
    ) -> IntegrityRecord | None:
        record = self._records.get(reference)
        if record is None or record.algorithm != algorithm:
            return None
        return record

    def verify_integrity(
        self,
        *,
        reference: str,
        digest: str,
        algorithm: str,
    ) -> LedgerStatus:
        record = self._records.get(reference)
        if record is None or record.algorithm != algorithm:
            return LedgerStatus.NOT_FOUND
        if record.digest == digest:
            return LedgerStatus.VERIFIED
        return LedgerStatus.MISMATCH

    def reset(self) -> None:
        """Clear recorded provenance (test isolation)."""
        self._records.clear()


__all__ = ["FakeLedger"]
