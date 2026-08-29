"""Shared helpers for LLM-backed Phase 7 generators.

Reduces duplication across generators: each generator supplies an output
schema class, a human label, and config; this helper assembles prompts,
invokes the LLM (via the injected provider, falling back to the deterministic
fake provider), validates the parsed JSON, and returns the JSON mapping ready
for persistence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.rag.schemas import RAGContext
from app.transformation.llm.fake import FakeLLMProvider
from app.transformation.llm.provider import LLMProvider
from app.transformation.output_schemas.parser import parse_output
from app.transformation.prompts.content import build_user_content
from app.transformation.prompts.loader import system_prompt


def generate_structured_output(
    *,
    output_type: str,
    schema_cls: type[BaseModel],
    output_name: str,
    canonical: dict[str, Any],
    config: dict[str, Any],
    rag_context: RAGContext | None,
    llm_provider: LLMProvider | None,
) -> dict[str, Any]:
    """Generate and validate a structured output for a single generator.

    Returns a JSON-compatible mapping (dict(model_dump)) ready to persist.
    Raises ValueError on empty/invalid output so the Phase 6 workflow records
    a controlled per-output failure.
    """
    provider = llm_provider if llm_provider is not None else FakeLLMProvider()

    fields = [f for f in schema_cls.model_fields if f != "text"]
    spec = "{" + ", ".join(fields) + ", text}"
    sp = system_prompt(output_name, spec, config)
    user = build_user_content(canonical, rag_context)

    generated = provider.generate_text(system_prompt=sp, user_content=user)
    if not generated or not generated.strip():
        raise ValueError(f"{output_name} provider returned empty output.")

    validated = parse_output(output_type, generated)
    data = validated.model_dump(mode="json")
    text = data.get("text")
    if not text or not str(text).strip():
        text = _fallback_text(output_name, data)
        data["text"] = text
    data["text"] = str(text)
    return data


def _fallback_text(output_name: str, data: dict[str, Any]) -> str:
    """Build a readable text rendering when the model omitted/blanked `text`."""
    title = data.get("title") or output_name
    lines = [f"# {title}", ""]
    for key in ("summary", "hook", "main_message", "situation", "script"):
        value = data.get(key)
        if value:
            lines.append(str(value))
            lines.append("")
    return "\n".join(lines).strip() or f"# {output_name}: {title}"
