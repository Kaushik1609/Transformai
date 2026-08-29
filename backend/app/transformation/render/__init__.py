"""Output rendering for Phase 7+.

* ``pptx``       — validated PresentationStructure -> real .pptx (Phase 8A)
* ``docx``       — Executive Summary / Advisory -> real .docx (Phase 8B)
* ``pdf``        — Executive Summary / Advisory -> real .pdf (Phase 8B)
* ``infographic``— validated Infographic -> real .pdf and .png (Phase 8C)
* ``video``      — validated VideoPackage -> structured video-package .pdf and
  companion .srt (Phase 8D)

All renderers are deterministic and LLM-free, consuming the validated Pydantic
schemas directly and returning file bytes for the storage abstraction.
"""

from __future__ import annotations
