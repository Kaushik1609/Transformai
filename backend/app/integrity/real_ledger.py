"""Phase 11M — RealLedger production boundary.

This adapter is interface-compatible with ``FakeLedger`` and is driven entirely
by environment-based configuration (``INTEGRITY_LEDGER_URL`` /
``INTEGRITY_LEDGER_CREDENTIAL``). It does NOT hard-code any network, RPC URL,
wallet, private key, contract address or credential.

PRODUCTION STATUS: CONFIGURATION-READY, NOT LIVE-VALIDATED.

Until a real ledger endpoint is supplied via the environment it refuses to
pretend a write succeeded: every call returns an explicit ``UNAVAILABLE`` /
``not recorded`` outcome so the provenance status honestly reflects the state.
Because no real blockchain integration has been exercised against a live node,
this adapter MUST NOT be reported as "blockchain verified".

The concrete wire protocol (submission endpoint, transaction-id parsing,
confirmation polling) lives in the deployment integration contract and is not
implemented here; when a live ledger is configured, an operator wires the
transport in this adapter and validates it against the real network before
enabling it in production.
"""

from __future__ import annotations

import logging

from app.integrity.ledger import IntegrityLedger, IntegrityRecord, LedgerStatus

logger = logging.getLogger(__name__)


class RealLedger(IntegrityLedger):
    """Environment-configured production provenance adapter (boundary).

    Requires ``INTEGRITY_LEDGER_URL`` to be set to a real target. Without it,
    operations return ``unavailable`` and never fake a recorded reference.
    """

    provider_name = "real"

    def __init__(self, *, ledger_url: str = "", credential: str = "") -> None:
        # credential is consumed here only to confirm configuration presence;
        # it is never logged, returned, hashed into a provenance reference, or
        # placed into any record/metric/API response.
        self._ledger_url = ledger_url or ""
        self._configured = bool(ledger_url)

    @property
    def configured(self) -> bool:
        """True only when a live ledger target has been supplied."""
        return self._configured

    def _unavailable(self, op: str) -> tuple[bool, IntegrityRecord | None, LedgerStatus]:
        logger.warning(
            "integrity ledger unavailable for %s (not configured)",
            op,
        )
        return False, None, LedgerStatus.UNAVAILABLE

    def record_integrity_event(
        self,
        *,
        digest: str,
        algorithm: str,
    ) -> tuple[bool, IntegrityRecord | None, LedgerStatus]:
        if not self._configured:
            return self._unavailable("record")
        # TODO(11M integration contract): submit digest to the configured ledger
        # and return the acknowledgement reference. Not implemented until a live
        # target is validated.
        return self._unavailable("record")

    def get_integrity_record(
        self,
        *,
        reference: str,
        algorithm: str,
    ) -> IntegrityRecord | None:
        if not self._configured:
            return None
        # TODO(11M integration contract): fetch the record by reference.
        return None

    def verify_integrity(
        self,
        *,
        reference: str,
        digest: str,
        algorithm: str,
    ) -> LedgerStatus:
        if not self._configured:
            return LedgerStatus.UNAVAILABLE
        # TODO(11M integration contract): compare ledger-held digest with the
        # submitted digest.
        return LedgerStatus.UNAVAILABLE


__all__ = ["RealLedger"]
