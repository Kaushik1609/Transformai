"""Output generator registry for Phase 6.

A small provider-independent registry mapping output_type -> Generator.
Phase 6 ships deterministic generators for summary, linkedin and advisory.
Additional output types defined by the repository (presentation, x,
infographic, video) are preserved but intentionally not implemented yet.
"""

from __future__ import annotations

from typing import Callable

from app.transformation.generators.advisory import AdvisoryGenerator
from app.transformation.generators.base import Generator
from app.transformation.generators.linkedin import LinkedInGenerator
from app.transformation.generators.summary import SummaryGenerator

_BUILTIN_GENERATORS: dict[str, type[Generator]] = {
    SummaryGenerator.output_type: SummaryGenerator,
    LinkedInGenerator.output_type: LinkedInGenerator,
    AdvisoryGenerator.output_type: AdvisoryGenerator,
}

# Known output types that Phase 6 does not generate sophisticated content for yet.
KNOWN_OUTPUT_TYPES = {
    "summary",
    "linkedin",
    "advisory",
    "x",
    "presentation",
    "infographic",
    "video",
}

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


def get_generator(output_type: str) -> Generator | None:
    """Return the generator for an output type, or None if unsupported."""
    for table in (_BUILTIN_GENERATORS, _EXTRA_GENERATORS):
        cls = table.get(output_type)
        if cls is not None:
            if _generator_factory is not None:
                return _generator_factory(cls)
            return cls()
    return None


def supported_output_types() -> list[str]:
    """Return output types that have a registered Phase 6 generator."""
    return sorted(_BUILTIN_GENERATORS)  # determinism over dict order


__all__ = [
    "Generator",
    "AdvisoryGenerator",
    "LinkedInGenerator",
    "SummaryGenerator",
    "KNOWN_OUTPUT_TYPES",
    "get_generator",
    "register_generator",
    "set_generator_factory",
    "supported_output_types",
]
