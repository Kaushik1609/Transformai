"""Deterministic LLM provider used for tests and offline/local development.

Produces a grounded, schema-valid JSON object from the supplied prompts
without any network access.  It inspects the field spec embedded in the
system prompt and the structured source brief in the user content, then
returns a deterministic payload that keeps important source facts intact.

This mirrors the Phase 4 FakeContentAnalysisProvider: deterministic output
that is already grounded in the source data so tests remain reliable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.transformation.llm.provider import LLMProvider

# Canonical scalar fields a generator may ask for, mapped to a deterministic
# source of truth where possible.
_SCALAR_HINTS: dict[str, str] = {
    "summary": "summary",
    "title": "title",
    "hook": "key_points",
    "main_message": "summary",
    "situation": "summary",
    "context": "summary",
    "call_to_action": "recommendations",
    "layout_recommendation": "recommendations",
}

_LIST_HINTS: dict[str, str] = {
    "key_findings": "key_points",
    "key_facts": "claims",
    "recommendations": "recommendations",
    "action_items": "recommendations",
    "supporting_points": "key_points",
    "hashtags": "topics",
    "thread": "key_points",
    "impact_risk": "key_points",
    "affected_parties": "entities",
    "recommended_actions": "recommendations",
    "key_messages": "key_points",
    "visual_suggestions": "topics",
    "visual_recommendations": "topics",
}


class FakeLLMProvider(LLMProvider):
    """Return a deterministic, source-grounded JSON object for the requested fields."""

    def generate_text(self, *, system_prompt: str, user_content: str) -> str:
        fields = self._extract_fields(system_prompt)
        source = self._parse_user_content(user_content)
        payload: dict[str, Any] = {"type": ""} if "type" in fields else {}
        for field in fields:
            if field == "type":
                continue
            if field in _SCALAR_HINTS:
                value = source.get(_SCALAR_HINTS[field])
                payload[field] = self._to_scalar(value, field)
            elif field == "text":
                payload[field] = self._build_text(source)
            elif field in {"slides", "sections", "storyboard"}:
                payload[field] = self._build_nested(field, source)
            elif field in _LIST_HINTS:
                values = source.get(_LIST_HINTS[field])
                payload[field] = self._to_list(values) or [f"Deterministic {field}"]
            else:
                payload[field] = self._default_scalar(field)
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fields(system_prompt: str) -> list[str]:
        match = re.search(r"fields:\s*\{([^}]*)\}", system_prompt)
        if match:
            return [f.strip() for f in match.group(1).split(",") if f.strip()]
        # Fallback: parse ANY { ... } token containing commas.
        fallback = re.search(r"\{([^}]+)\}", system_prompt)
        if fallback:
            return [f.strip() for f in fallback.group(1).split(",") if f.strip()]
        return ["title", "text"]

    @staticmethod
    def _parse_user_content(user_content: str) -> dict[str, Any]:
        source: dict[str, Any] = {}
        title_match = re.search(r"^TITLE:\s*(.+)$", user_content, re.MULTILINE)
        source["title"] = title_match.group(1).strip() if title_match else "Untitled source"
        summary_match = re.search(r"^SUMMARY:\s*(.+)$", user_content, re.MULTILINE)
        source["summary"] = summary_match.group(1).strip() if summary_match else ""

        for label, key in (
            ("KEY POINTS:", "key_points"),
            ("CLAIMS:", "claims"),
            ("STATISTICS:", "statistics"),
            ("DATES:", "dates"),
            ("RECOMMENDATIONS/ACTIONS:", "recommendations"),
            ("TOPICS:", "topics"),
            ("ENTITIES:", "entities"),
        ):
            source[key] = FakeLLMProvider._extract_bullets(user_content, label)
        return source

    @staticmethod
    def _extract_bullets(user_content: str, label: str) -> list[str]:
        lines = user_content.splitlines()
        output: list[str] = []
        capture = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(label):
                capture = True
                continue
            if capture:
                if stripped.startswith("- "):
                    output.append(stripped[2:].strip())
                elif stripped == "":
                    continue
                elif not stripped.startswith("-"):
                    break
        return output

    @staticmethod
    def _to_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v]
        return [str(value)]

    @classmethod
    def _to_scalar(cls, value: Any, field: str) -> str:
        """Coerce a source value to a string required by a scalar field."""
        if isinstance(value, list):
            for item in value:
                if item:
                    return str(item)
            return cls._default_scalar(field)
        if value:
            return str(value)
        return cls._default_scalar(field)

    @staticmethod
    def _default_scalar(field: str) -> str:
        return f"Deterministic {field.replace('_', ' ')}"

    @classmethod
    def _build_text(cls, source: dict[str, Any]) -> str:
        title = source.get("title") or "Untitled source"
        summary = source.get("summary") or "(no summary available)"
        lines = [title, "", summary]
        for label in ("key_points", "recommendations"):
            values = cls._to_list(source.get(label))
            if values:
                lines.append("")
                lines.extend(f"- {v}" for v in values)
        return "\n".join(lines)

    @classmethod
    def _build_nested(cls, kind: str, source: dict[str, Any]) -> list[dict[str, Any]]:
        """Build a deterministic nested structure for slides/sections/storyboard."""
        items = cls._to_list(source.get("key_points")) or ["Key message one", "Key message two"]
        nested: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if kind == "slides":
                nested.append(
                    {
                        "title": f"Slide {index + 1}",
                        "key_message": item,
                        "supporting_points": [],
                        "visual_recommendation": "Chart or diagram",
                        "speaker_notes": [f"Explain: {item}"],
                    }
                )
            elif kind == "sections":
                nested.append(
                    {
                        "heading": f"Section {index + 1}",
                        "message": item,
                        "visual_suggestion": "Icon or chart",
                    }
                )
            else:  # storyboard
                nested.append(
                    {
                        "title": f"Scene {index + 1}",
                        "description": item,
                        "narration": f"Narrate: {item}",
                        "subtitle": item,
                        "visual_recommendation": "B-roll footage",
                    }
                )
        return nested
