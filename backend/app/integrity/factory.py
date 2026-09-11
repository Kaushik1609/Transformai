"""Phase 11M — build the configured provenance ledger."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from app.core.config import settings
from app.integrity.fake_ledger import FakeLedger
from app.integrity.ledger import IntegrityLedger
from app.integrity.real_ledger import RealLedger


def build_ledger() -> Optional[IntegrityLedger]:
    """Return the configured ledger, or None when integrity is disabled.

    Selection is driven by ``INTEGRITY_PROVIDER``:

      * ``fake`` — deterministic offline FakeLedger (unit tests / local dev).
      * ``real`` — RealLedger production boundary. Without ``INTEGRITY_LEDGER_URL``
        it reports ``unavailable``; it never fabricates a recorded reference.
      * ``none`` — no ledger adapter (returns None); local hash + verification
        still work via ``integrity/service.py``.
    """
    provider = settings.INTEGRITY_PROVIDER
    if provider == "fake":
        return FakeLedger()
    if provider == "real":
        return RealLedger(
            ledger_url=settings.INTEGRITY_LEDGER_URL,
            credential=settings.INTEGRITY_LEDGER_CREDENTIAL,
        )
    return None


@lru_cache(maxsize=1)
def get_ledger() -> Optional[IntegrityLedger]:
    """Memoized ledger (process-wide, mirrors the settings singleton)."""
    return build_ledger()


__all__ = ["build_ledger", "get_ledger"]
