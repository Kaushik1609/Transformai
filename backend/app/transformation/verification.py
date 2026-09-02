"""Phase 8 verification hook — workflow integration point.

Replaces the Phase 6 stub.  The hook delegates to the deterministic Phase 8
verification engine (claim extraction, source-evidence grounding, consistency
analysis, and warning generation) whenever the workflow reaches
    generate -> validate -> verify_hook

The external contract is preserved: ``VerificationHook.verify`` and
``run_verification_hook`` keep their signatures, and output records now receive
real scores, claims, and warnings instead of the old ``pending_phase8`` marker.
"""

from __future__ import annotations

from typing import Any

from app.transformation.verification_engine.engine import RESULT_COMPLETED, run_verification

# The engine result uses this marker for details["status"].
VERIFICATION_COMPLETED = RESULT_COMPLETED


class VerificationHook:
    """Run the real Phase 8 verification engine for a generated output.

    The hook can be constructed with a fixed set of source chunks (for tests
    and simple callers) or receive ``source_chunks`` per call from the graph.
    """

    def __init__(self, *, source_chunks: list[str] | None = None) -> None:
        self.source_chunks: list[str] = list(source_chunks or [])

    def verify(
        self,
        *,
        output: dict[str, Any],
        canonical: dict[str, Any],
        source_chunks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a real verification result for one generated output."""
        chunks = list(source_chunks) if source_chunks is not None else self.source_chunks
        result = run_verification(
            output=output,
            canonical=canonical,
            source_chunks=chunks,
        )
        return {
            "output_type": output.get("type", ""),
            **result,
        }


def run_verification_hook(
    *,
    output: dict[str, Any],
    canonical: dict[str, Any],
    hook: VerificationHook | None = None,
    source_chunks: list[str] | None = None,
) -> dict[str, Any]:
    """Run the verification hook for a single output."""
    instance = hook or VerificationHook()
    return instance.verify(
        output=output,
        canonical=canonical,
        source_chunks=source_chunks,
    )