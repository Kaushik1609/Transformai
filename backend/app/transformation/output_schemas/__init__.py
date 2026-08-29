"""Validated Pydantic contracts for Phase 7 output generators.

Each output type has its own schema.  The `type` discriminator routes
persistence/rendering; `text` is the canonical human-readable representation
that is always persisted to `Output.text_content`.  `title` and `text` are
required so a completed output always has usable human content (enforced by
the Phase 6 validate stage).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SharedConfig = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 1. Executive Summary
# ---------------------------------------------------------------------------

class ExecutiveSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "summary"
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    context: str = ""
    key_findings: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 2. LinkedIn Post
# ---------------------------------------------------------------------------

class LinkedInPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "linkedin"
    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    main_message: str = Field(min_length=1)
    supporting_points: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    hashtags: list[str] = Field(default_factory=list)
    body: str = Field(min_length=1)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 3. Advisory
# ---------------------------------------------------------------------------

class Advisory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "advisory"
    title: str = Field(min_length=1)
    situation: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list)
    impact_risk: list[str] = Field(default_factory=list)
    affected_parties: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 4. Presentation structure
# ---------------------------------------------------------------------------

class PresentationSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    key_message: str = ""
    supporting_points: list[str] = Field(default_factory=list)
    visual_recommendation: str = ""
    speaker_notes: list[str] = Field(default_factory=list)


class PresentationStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "presentation"
    title: str = Field(min_length=1)
    slides: list[PresentationSlide] = Field(min_length=1)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 5. X / Twitter
# ---------------------------------------------------------------------------

class XPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "x"
    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    main_message: str = Field(min_length=1)
    supporting_points: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    hashtags: list[str] = Field(default_factory=list)
    thread: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 6. Infographic
# ---------------------------------------------------------------------------

class InfographicSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    message: str = Field(min_length=1)
    visual_suggestion: str = ""


class Infographic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "infographic"
    title: str = Field(min_length=1)
    key_messages: list[str] = Field(min_length=1)
    sections: list[InfographicSection] = Field(min_length=1)
    layout_recommendation: str = Field(min_length=1)
    visual_suggestions: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 7. Video package
# ---------------------------------------------------------------------------

class VideoScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    narration: str = Field(min_length=1)
    subtitle: str = Field(min_length=1)
    visual_recommendation: str = ""


class VideoPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "video"
    title: str = Field(min_length=1)
    script: str = Field(min_length=1)
    storyboard: list[VideoScene] = Field(min_length=1)
    narration_full: str = Field(min_length=1)
    subtitles_full: str = Field(min_length=1)
    visual_recommendations: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Discriminator values for the `type` field
# ---------------------------------------------------------------------------
ALL_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "summary": ExecutiveSummary,
    "linkedin": LinkedInPost,
    "advisory": Advisory,
    "presentation": PresentationStructure,
    "x": XPost,
    "infographic": Infographic,
    "video": VideoPackage,
}


def build_text_message(schema: type[BaseModel]) -> str:
    """Return a prompt line describing the required output fields.

    Used to guide the LLM and FakeLLMProvider toward the expected structure.
    """
    return ", ".join(field for field in schema.model_fields if field != "text")


__all__ = [
    "ExecutiveSummary",
    "LinkedInPost",
    "Advisory",
    "PresentationStructure",
    "PresentationSlide",
    "XPost",
    "Infographic",
    "InfographicSection",
    "VideoPackage",
    "VideoScene",
    "ALL_OUTPUT_SCHEMAS",
]
