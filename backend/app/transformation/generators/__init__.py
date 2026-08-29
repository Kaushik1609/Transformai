"""Output generator registry.

A small provider-independent registry mapping output_type -> Generator.
Phase 6 shipped deterministic generators for summary, linkedin and advisory.
Phase 7 upgrades those to use the LLM layer and adds presentation, x,
infographic and video generators — all 7 registered here.
"""

from __future__ import annotations

from typing import Callable

from app.transformation.generators.advisory import AdvisoryGenerator
from app.transformation.generators.base import Generator
from app.transformation.generators.infographic import InfographicGenerator
from app.transformation.generators.linkedin import LinkedInGenerator
from app.transformation.generators.presentation import PresentationGenerator
from app.transformation.generators.summary import SummaryGenerator
from app.transformation.generators.video import VideoGenerator
from app.transformation.generators.x import XGenerator
from app.transformation.llm.provider import LLMProvider

_BUILTIN_GENERATORS: dict[str, type[Generator]] = {
    SummaryGenerator.output_type: SummaryGenerator,
    LinkedInGenerator.output_type: LinkedInGenerator,
    AdvisoryGenerator.output_type: AdvisoryGenerator,
    PresentationGenerator.output_type: PresentationGenerator,
    XGenerator.output_type: XGenerator,
    InfographicGenerator.output_type: InfographicGenerator,
    VideoGenerator.output_type: VideoGenerator,
}

# All output types the platform knows about (Phase 7 implements all of them).
KNOWN_OUTPUT_TYPES = frozenset(_BUILTIN_GENERATORS)

# Custom registry hook so tests/plugins can register additional generators.
_EXTRA_GENERATORS: dict[str, type[Generator]] = {}
# Factory hook to allow tests to inject failing/stub generators.
_generator_factory: Callable[[type[Generator]], Generator] | None = None


def register_generator(output_type: str, generator_cls: type[Generator]) -> None:
    """Register an additional generator class by output type."""
    _EXTRA_GENERATORS[output_type] = generator_cls


def set_generator_factory(factory: Callable[[type[Generator]], Generator] | None) -> None:
    """Override how generator instances are constructed (test hook)."""
    global _generator_factory
    _generator_factory = factory


def get_generator(
    output_type: str,
    llm_provider: LLMProvider | None = None,
) -> Generator | None:
    """Return the generator for an output type, or None if unsupported.

    When `llm_provider` is supplied it is injected into the generator via the
    constructor; when absent the generator uses its deterministic fallback.
    """
    for table in (_BUILTIN_GENERATORS, _EXTRA_GENERATORS):
        cls = table.get(output_type)
        if cls is not None:
            if _generator_factory is not None:
                return _generator_factory(cls)
            return cls(llm_provider=llm_provider)
    return None


def supported_output_types() -> list[str]:
    """Return output types that have a registered generator."""
    return sorted(_BUILTIN_GENERATORS)  # determinism over dict order


__all__ = [
    "Generator",
    "SummaryGenerator",
    "LinkedInGenerator",
    "AdvisoryGenerator",
    "PresentationGenerator",
    "XGenerator",
    "InfographicGenerator",
    "VideoGenerator",
    "KNOWN_OUTPUT_TYPES",
    "get_generator",
    "register_generator",
    "set_generator_factory",
    "supported_output_types",
]
