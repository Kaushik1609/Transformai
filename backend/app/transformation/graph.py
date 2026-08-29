"""LangGraph transformation workflow for Phase 6.

Stage flow:
    load_input
      -> retrieve_if_required (only when RAG is required)
      -> generate
      -> validate
      -> verify_hook
      -> finalize

The orchestrator owns coordination; the graph nodes implement each stage.
DB access (authoritative state) is injected through TransformationDependencies
so the same workflow runs from the worker and from tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.canonical_content import CanonicalContent
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.output import Output
from app.db.models.transformation_job import TransformationJob
from app.db.models.verification_result import VerificationResult
from app.rag.service import RAGService
from app.transformation.artifacts import get_storage, save_output_artifact
from app.transformation.output_schemas import PresentationStructure
from app.transformation.render.pptx import PPTX_MIME_TYPE, render_presentation
from app.transformation.schemas import TransformationState
from app.transformation.verification import VerificationHook, run_verification_hook


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TransformationDependencies:
    """Dependencies injected into the transformation workflow."""

    session: Session
    rag_service: RAGService | None = None
    verification_hook: VerificationHook | None = None
    get_generator: Callable[[str], Any | None] | None = None
    rag_mode: str = "auto"  # "auto" | "always-on" | "off"
    llm_provider: Any | None = None
    storage: Any | None = None
    # Optional overrides for deterministic tests.
    requested_output_types_override: list[str] | None = None
    rag_required_override: bool | None = None

    def __post_init__(self) -> None:
        if self.rag_service is None:
            self.rag_service = RAGService()
        if self.get_generator is None:
            from app.transformation.generators import get_generator as _registry

            provider = self.llm_provider
            self.get_generator = lambda output_type: _registry(
                output_type, llm_provider=provider
            )
        if self.storage is None:
            self.storage = get_storage()


class TransformationWorkflow:
    """Implements each LangGraph node for the transformation pipeline."""

    def __init__(self, deps: TransformationDependencies):
        self.deps = deps

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def load_input(self, state: TransformationState) -> TransformationState:
        session = self.deps.session
        job = session.get(TransformationJob, uuid.UUID(state["job_id"]))
        if job is None:
            raise ValueError(f"Transformation job {state['job_id']} was not found.")

        # Transition to running as soon as a worker begins.
        job.status = "running"
        job.started_at = _utcnow()

        requested = self.deps.requested_output_types_override or list(
            job.requested_outputs.get("output_types", []) if job.requested_outputs else []
        )

        project_id = str(job.project_id)
        source_id = str(job.source_id)
        configuration_id = str(job.configuration_id)

        # Load user configuration for generation context.
        config: dict[str, Any] = {}
        config_record = session.get(GenerationConfiguration, job.configuration_id)
        if config_record is not None:
            config = {
                "target_audience": config_record.target_audience,
                "tone": config_record.tone,
                "language": config_record.language,
                "detail_level": config_record.detail_level,
                "communication_objective": config_record.communication_objective,
                "content_style": config_record.content_style,
                "custom_instructions": config_record.custom_instructions,
            }

        session.flush()
        return {
            "job_id": state["job_id"],
            "project_id": project_id,
            "source_id": source_id,
            "configuration_id": configuration_id,
            "requested_output_types": requested,
            "config": config,
            "canonical_ready": False,
            "canonical_missing": False,
            "outputs": [],
            "errors": [],
            "verification_hooks": [],
            "rag_required": self._rag_required(config, job),
        }

    def _rag_required(self, config: dict[str, Any], job: TransformationJob) -> bool:
        if self.deps.rag_required_override is not None:
            return self.deps.rag_required_override
        mode = self.deps.rag_mode
        if mode == "always-on":
            return True
        if mode == "off":
            return False
        # auto: use RAG for detailed/large-format or decision-support outputs
        meta = job.requested_outputs or {}
        if meta.get("use_rag") is True:
            return True
        objective = (config.get("communication_objective") or "").lower()
        return objective in {"decision support", "education"}

    def load_canonical_content(self, state: TransformationState) -> TransformationState:
        session = self.deps.session
        result = session.execute(
            select(CanonicalContent).where(CanonicalContent.source_id == uuid.UUID(state["source_id"]))
        ).scalar_one_or_none()

        canonical: dict[str, Any] = {}
        if result is None:
            state["canonical_missing"] = True
            state["canonical_ready"] = False
            state["errors"] = [
                {
                    "stage": "load_canonical_content",
                    "message": "Canonical content is missing for the source.",
                }
            ]
            return state

        if result.status != "completed":
            state["canonical_missing"] = True
            state["canonical_ready"] = False
            state["errors"] = [
                {
                    "stage": "load_canonical_content",
                    "message": (
                        f"Canonical content is not completed (status: {result.status!r}). "
                        "Run content intelligence before transforming."
                    ),
                }
            ]
            return state

        canonical = {
            "id": str(result.id),
            "source_id": str(result.source_id),
            "title": result.title,
            "summary": result.summary,
            "topics": result.topics or [],
            "entities": result.entities or [],
            "key_points": result.key_points or [],
            "claims": result.claims or [],
            "statistics": result.statistics or [],
            "dates": result.dates or [],
            "recommendations": result.recommendations or [],
            "source_references": result.source_references or [],
        }
        return {"canonical": canonical, "canonical_ready": True, "canonical_missing": False}

    def retrieve_if_required(self, state: TransformationState) -> TransformationState:
        """Retrieve RAG context only when required by the transformation."""
        if not state.get("canonical_ready"):
            return {}
        if not state.get("rag_required"):
            return {}

        session = self.deps.session
        source_id = uuid.UUID(state["source_id"])
        project_id = uuid.UUID(state["project_id"])
        query = state.get("canonical", {}).get("summary") or state.get("canonical", {}).get("title") or source_id.__str__()
        task_context = "; ".join(
            f"{k}: {v}" for k, v in state.get("config", {}).items() if v
        )

        try:
            context = self.deps.rag_service.retrieve_context_for_source(
                session,
                source_id,
                query,
                project_id=project_id,
                top_k=5,
                task_context=task_context or None,
            )
            return {"rag_context": context}
        except Exception as exc:  # retrieval is best-effort; never corrupt source
            return {
                "errors": [
                    {
                        "stage": "retrieve_if_required",
                        "message": f"RAG retrieval failed: {exc}",
                    }
                ]
            }

    def generate(self, state: TransformationState) -> TransformationState:
        session = self.deps.session
        if not state.get("canonical_ready"):
            return {}

        canonical = state["canonical"]
        config = state.get("config", {})
        rag_context = state.get("rag_context")

        outputs: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = list(state.get("errors", []))

        for output_type in state.get("requested_output_types", []):
            job_id = uuid.UUID(state["job_id"])
            output = Output(
                id=uuid.uuid4(),
                job_id=job_id,
                output_type=output_type,
                status="generating",
                created_at=_utcnow(),
            )
            session.add(output)
            session.flush()

            generator = self.deps.get_generator(output_type) if self.deps.get_generator else None
            if generator is None:
                output.status = "failed"
                output.error_message = f"No generator registered for output type {output_type!r}."
                errors.append(
                    {
                        "stage": "generate",
                        "output_type": output_type,
                        "message": output.error_message,
                    }
                )
                session.flush()
                outputs.append(
                    {
                        "output_id": str(output.id),
                        "output_type": output_type,
                        "status": "failed",
                    }
                )
                continue

            try:
                generated = generator.generate(
                    canonical=canonical,
                    config=config,
                    rag_context=rag_context,
                )
                text_content = generated.get("text", "")
                if not isinstance(text_content, str) or not text_content.strip():
                    raise ValueError("Generator produced empty text content.")

                output.structured_content = generated
                output.text_content = text_content
                output.mime_type = generated.get("mime_type") or "text/plain"
                output.output_metadata = {
                    "provider": "phase7",
                    "generator": type(generator).__name__,
                }
                self._persist_presentation_artifact(
                    state, output, generated,
                    project_id=uuid.UUID(state["project_id"]),
                    job_id=job_id,
                )
                output.status = "completed"
                session.flush()

                outputs.append(
                    {
                        "output_id": str(output.id),
                        "output_type": output_type,
                        "status": "completed",
                        "structured_content": generated,
                        "text_content": text_content,
                    }
                )
            except Exception as exc:
                output.status = "failed"
                output.error_message = str(exc)[:4000]
                errors.append(
                    {
                        "stage": "generate",
                        "output_type": output_type,
                        "message": output.error_message,
                    }
                )
                session.flush()
                outputs.append(
                    {
                        "output_id": str(output.id),
                        "output_type": output_type,
                        "status": "failed",
                    }
                )

        return {"outputs": outputs, "errors": errors}

    def _persist_presentation_artifact(
        self,
        state: TransformationState,
        output: Output,
        generated: dict[str, Any],
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Render and store a PPTX artifact for completed presentation outputs.

        Only presentation outputs produce a binary artifact; all other output
        types are persisted entirely in the `outputs` table.  Raises on a
        render/persist failure so the caller's existing generate-stage error
        handling records a controlled per-output failure without destroying
        other outputs in the same job.
        """
        if output.output_type != "presentation":
            return
        structure = PresentationStructure.model_validate(generated)
        pptx_bytes = render_presentation(structure)
        key = save_output_artifact(
            project_id=project_id,
            job_id=job_id,
            output_id=output.id,
            mime_type=PPTX_MIME_TYPE,
            content=pptx_bytes,
            storage=self.deps.storage,
        )
        output.mime_type = PPTX_MIME_TYPE
        output.storage_key = key
        output.output_metadata = {
            **(output.output_metadata or {}),
            "artifact": "pptx",
            "bytes": len(pptx_bytes),
        }

    def validate(self, state: TransformationState) -> TransformationState:
        """Light structural validation of completed outputs.

        A completed output that no longer has usable text is flagged as failed.
        This never destroys successful outputs from the same job (partial success).
        """
        session = self.deps.session
        if not state.get("outputs"):
            return {}

        errors = list(state.get("errors", []))
        outputs: list[dict[str, Any]] = []
        for output in state["outputs"]:
            if output["status"] != "completed":
                outputs.append(output)
                continue
            if not output.get("structured_content"):
                record = session.get(Output, uuid.UUID(output["output_id"]))
                if record is not None:
                    record.status = "failed"
                    record.error_message = "Validation failed: no structured content."
                    session.flush()
                errors.append(
                    {
                        "stage": "validate",
                        "output_type": output["output_type"],
                        "message": "Validation failed: no structured content.",
                    }
                )
                continue
            outputs.append(output)

        return {"outputs": outputs, "errors": errors}

    def verify_hook(self, state: TransformationState) -> TransformationState:
        """Invoke the Phase 6 verification hook for each completed output."""
        session = self.deps.session
        hooks: list[dict[str, Any]] = list(state.get("verification_hooks", []))

        for output in state.get("outputs", []):
            if output["status"] != "completed":
                continue
            result = run_verification_hook(
                output=output["structured_content"],
                canonical=state.get("canonical", {}),
                hook=self.deps.verification_hook,
            )
            hooks.append(
                {
                    "output_id": output["output_id"],
                    "output_type": output["output_type"],
                    "result": result,
                }
            )
            # Persist a verification result record reusing the existing model.
            record = session.get(Output, uuid.UUID(output["output_id"]))
            if record is not None:
                session.add(
                    VerificationResult(
                        id=uuid.uuid4(),
                        output_id=record.id,
                        overall_status="warning",
                        claims_checked=0,
                        claims_supported=0,
                        warnings={"status": result["status"], "message": result["message"]},
                        details=result,
                        created_at=_utcnow(),
                    )
                )
                session.flush()

        return {"verification_hooks": hooks}

    def finalize(self, state: TransformationState) -> TransformationState:
        """Update job status based on canonical readiness and output outcomes."""
        session = self.deps.session
        job = session.get(TransformationJob, uuid.UUID(state["job_id"]))
        if job is None:
            return {}

        completed = sum(1 for o in state.get("outputs", []) if o["status"] == "completed")
        requested = len(state.get("requested_output_types", []))

        if not state.get("canonical_ready"):
            job.status = "failed"
            job.progress = 100
            job.error_message = "Canonical content is missing or not completed; cannot transform."
            job.completed_at = _utcnow()
            session.flush()
            return {"errors": state.get("errors", [])}

        failures = sum(1 for o in state.get("outputs", []) if o["status"] == "failed")

        if completed >= 1:
            # Partial success: keep successful outputs, mark job completed.
            job.status = "completed"
            job.progress = 100
        elif requested == 0:
            job.status = "failed"
            job.error_message = "No output types were requested."
            job.progress = 100
        else:
            job.status = "failed"
            job.error_message = f"All {requested} requested outputs failed ({failures} failed)."
            job.progress = 100
        job.completed_at = _utcnow()
        session.flush()
        return {}


def build_transformation_graph(deps: TransformationDependencies):
    """Build and compile the LangGraph transformation workflow."""
    workflow = TransformationWorkflow(deps)

    builder = StateGraph(TransformationState)

    builder.add_node("load_input", workflow.load_input)
    builder.add_node("load_canonical_content", workflow.load_canonical_content)
    builder.add_node("retrieve_if_required", workflow.retrieve_if_required)
    builder.add_node("generate", workflow.generate)
    builder.add_node("validate", workflow.validate)
    builder.add_node("verify_hook", workflow.verify_hook)
    builder.add_node("finalize", workflow.finalize)

    builder.set_entry_point("load_input")
    builder.add_edge("load_input", "load_canonical_content")

    def _after_canonical(state: TransformationState) -> str:
        return "retrieve_if_required" if state.get("canonical_ready") else "finalize"

    builder.add_conditional_edges(
        "load_canonical_content",
        _after_canonical,
        {"retrieve_if_required": "retrieve_if_required", "finalize": "finalize"},
    )
    builder.add_edge("retrieve_if_required", "generate")
    builder.add_edge("generate", "validate")
    builder.add_edge("validate", "verify_hook")
    builder.add_edge("verify_hook", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
