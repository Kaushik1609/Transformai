"""Phase 8 verification engine.

Deterministic, offline claim extraction + grounding + consistency analysis for
generated outputs.  See ``engine.run_verification`` for the pipeline, and
``transformation.verification`` for the workflow hook integration point.
"""

from app.transformation.verification_engine.engine import (
    RESULT_COMPLETED,
    STATUS_PASSED,
    STATUS_WARNING,
    run_verification,
)

__all__ = [
    "RESULT_COMPLETED",
    "STATUS_PASSED",
    "STATUS_WARNING",
    "run_verification",
]