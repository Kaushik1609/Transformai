"""Transformation orchestrator — coordinates the LangGraph workflow.

The orchestrator is responsible for workflow coordination only.  It builds the
LangGraph graph with the authoritative DB session and injected services, runs
it for a single transformation job, and commits the resulting state.  Detailed
output-specific prompt/generation logic lives in the generators, never here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.rag.service import RAGService
from app.transformation.graph import TransformationDependencies, build_transformation_graph


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransformationOrchestrator:
    """Coordinate one transformation job through the LangGraph workflow."""

    def __init__(
        self,
        *,
        session: Session,
        rag_service: RAGService | None = None,
        verification_hook: Any | None = None,
        get_generator: Any | None = None,
        rag_mode: str = "auto",
        llm_provider: Any | None = None,
        storage: Any | None = None,
        requested_output_types_override: list[str] | None = None,
        rag_required_override: bool | None = None,
    ):
        self.deps = TransformationDependencies(
            session=session,
            rag_service=rag_service,
            verification_hook=verification_hook,
            get_generator=get_generator,
            rag_mode=rag_mode,
            llm_provider=llm_provider,
            storage=storage,
            requested_output_types_override=requested_output_types_override,
            rag_required_override=rag_required_override,
        )
        self.graph = build_transformation_graph(self.deps)

    def execute(self, job_id: uuid.UUID) -> dict[str, Any]:
        """Run the workflow for a job and return a summary of the outcome.

        The caller (worker or test) owns the session/transaction commit.
        """
        initial_state: dict[str, Any] = {"job_id": str(job_id)}
        result = self.graph.invoke(initial_state)

        completed = sum(1 for o in result.get("outputs", []) if o["status"] == "completed")
        failed = sum(1 for o in result.get("outputs", []) if o["status"] == "failed")

        return {
            "job_id": str(job_id),
            "canonical_ready": bool(result.get("canonical_ready", False)),
            "outputs_completed": completed,
            "outputs_failed": failed,
            "outputs": result.get("outputs", []),
            "errors": result.get("errors", []),
            "verification_hooks": result.get("verification_hooks", []),
        }
