"""Phase 11M — provenance ledger abstraction.

This module is the POST-GENERATION integrity/provenance layer. It never hooks
into LLM generation, RAG retrieval, prompt construction, provider selection or
output-schema validation — the AI pipeline stays untouched. The ledger records
and verifies a content digest AFTER an artifact has already been persisted.

The transformation layer depends only on this abstraction; it never sees any
blockchain-specific detail. Three operations are supported:

  * ``record_integrity_event`` — submit a content digest to the configured
    ledger and return an opaque provenance reference.
  * ``get_integrity_record``   — fetch a previously recorded provenance record.
  * ``verify_integrity``       — confirm a digest is recorded on the ledger.

The outcome of every ledger call is expressed with an explicit
``LedgerStatus`` so callers can always distinguish:

  * ``recorded``       — the write was acknowledged
  * ``unavailable``    — the ledger could not be reached (never silently forged)
  * ``not_found``      — no matching record
  * ``verified``       — recorded digest matches the submitted digest
  * ``mismatch``       — recorded digest does not match
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class LedgerStatus(str, enum.Enum):
    """Discrete provenance outcomes (never conflated with each other)."""

    RECORDED = "recorded"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    VERIFIED = "verified"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class IntegrityRecord:
    """A proven integrity/provenance record for one artifact digest.

    Only safe provenance references are carried here — never credentials,
    private keys, RPC endpoints with secrets, or full artifact contents.
    ``reference`` is the opaque ledger transaction/reference identifier.
    """

    reference: str
    digest: str
    algorithm: str
    provider: str
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class IntegrityLedger:
    """Abstract provenance ledger.

    Concrete implementations must be deterministic (identical input yields the
    same reference for FakeLedger) and must never raise for a merely-unavailable
    backend — instead they return a ``recorded=False`` / ``unavailable`` result
    so the caller can reflect the true provenance status.
    """

    provider_name: str = "abstract"

    def record_integrity_event(
        self,
        *,
        digest: str,
        algorithm: str,
    ) -> tuple[bool, IntegrityRecord | None, LedgerStatus]:
        """Record ``digest`` and return (recorded, record, status)."""
        raise NotImplementedError

    def get_integrity_record(
        self,
        *,
        reference: str,
        algorithm: str,
    ) -> IntegrityRecord | None:
        """Return the recorded record for ``reference`` or None."""
        raise NotImplementedError

    def verify_integrity(
        self,
        *,
        reference: str,
        digest: str,
        algorithm: str,
    ) -> LedgerStatus:
        """Verify that the ledger holds ``digest`` for ``reference``."""
        raise NotImplementedError


# Re-exported convenience aliases so callers can use the enums without importing
# the module internals twice.
__all__ = [
    "IntegrityLedger",
    "IntegrityRecord",
    "LedgerStatus",
]
