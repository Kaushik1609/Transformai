"""Deterministic provider used by tests and local development."""

from __future__ import annotations

from app.content_intelligence.provider import ContentAnalysisProvider


class FakeContentAnalysisProvider(ContentAnalysisProvider):
    """Produce grounded, deterministic content without network access."""

    def analyze(self, text: str, chunks: list[dict]) -> dict:
        first_chunk = chunks[0]
        evidence = first_chunk["content"][:240]
        reference = [str(first_chunk["id"])]
        return {
            "title": text.strip().splitlines()[0][:200],
            "summary": text.strip()[:500],
            "metadata": {"provider": "fake", "analysis_version": "phase4-v1"},
            "topics": [{"value": "source content", "source_chunk_ids": reference}],
            "entities": [],
            "key_points": [{"text": evidence, "source_chunk_ids": reference, "evidence": evidence}],
            "claims": [{"text": evidence, "source_chunk_ids": reference, "evidence": evidence}],
            "statistics": [],
            "dates": [],
            "recommendations": [],
            "source_references": [{"text": evidence, "source_chunk_ids": reference, "evidence": evidence}],
        }
