# Evidence Verification (Phase 11N)

Deterministic, evidence-based fact verification for generated transformation
outputs. Reports whether each factual claim is supported, contradicted, or
unverified relative to the project's own ingested source documents — **not**
a claim of ground-truth correctness.

---

## Overview

When a user clicks **Verify facts** on a completed output, the frontend calls:

```
POST /api/v1/outputs/{output_id}/verify-facts
```

The endpoint:

1. Extracts factual claims from `output.structured_content` (or `text_content`)
   using `app.transformation.verification_engine.claims.extract_claims`.
2. Retrieves source-scoped evidence from the project's RAG embeddings via
   `RAGService.retrieve_context_for_source`.
3. Matches each claim against the evidence using lexical overlap and
   numeric/date consistency checks (mirrors `evidence.py` Phase 8 logic).
4. Assigns one of three verdicts to each claim:
   - **SUPPORTED** — strong overlap (≥ 0.55) with no numeric/date conflict.
   - **CONTRADICTED** — subset-mismatch on claim numbers or dates against the
     strongest-overlapping chunk.
   - **UNVERIFIED** — no overlapping evidence retrieved.
5. Persists a `VerificationResult` row (reuses the Phase 8 table, no migration).
6. Returns a bounded `FactVerificationResponse` with per-claim verdicts and
   evidence snippets.

---

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `FACT_VERIFICATION_ENABLED` | `True` | Master kill-switch; POST returns 409 when disabled. |
| `FACT_VERIFICATION_MAX_CLAIMS` | `20` | Maximum claims processed per invocation. |
| `FACT_VERIFICATION_TOP_K` | `3` | RAG retrieval top-k per claim. |
| `FACT_VERIFICATION_MIN_SIMILARITY` | `0.0` | Minimum cosine similarity threshold passed to RAG. |
| `FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM` | `3` | Maximum evidence chunks surfaced per claim. |

---

## Verdict logic

The engine reuses the same numeric/date extraction and conflict detection as
Phase 8's `evidence.py`, ensuring consistency across the verification pipeline.

| Condition | Verdict |
|---|---|
| Overlap ≥ 0.55 **and** numeric/date fields match or absent | SUPPORTED |
| Chunk numbers/dates are a strict superset of claim numbers/dates | CONTRADICTED |
| No retrieved evidence overlaps strongly | UNVERIFIED |

---

## Metrics

Three counter families exposed at `/metrics`:

| Family | Labels |
|---|---|
| `fact_verification_requests_total` | `result` (`completed` / `failed`) |
| `fact_verification_claims_total` | `verdict` (`SUPPORTED` / `CONTRADICTED` / `UNVERIFIED`) |
| `fact_verification_results_total` | `status` (`passed` / `warning` / `failed`) |

---

## Storage

The report is persisted into the existing `verification_results` table with:

- `generator = "deterministic-phase11n-factcheck"`
- `grounding_score = claims_supported / claims_checked` (or 0)
- `details.claims` — full per-claim verdict, reason, overlap, and evidence list
- `warnings.items` — one entry per non-supported claim

No database migration is required; the table was introduced in Phase 8.

## Audit events

The Phase 11N operation emits three Phase 11K security/audit events through the
existing `app.core.audit.emit_security_event` sink (no second audit system):

| Event | Outcome | When |
|---|---|---|
| `fact_verification_started` | `started` | A valid verification run begins (after guards pass). |
| `fact_verification_completed` | `completed` | After a report is produced and persisted. |
| `fact_verification_failed` | `failed` | Unexpected engine/retrieval/persistence failure. |

A normal `UNVERIFIED` claim verdict is **not** a failure — the report is still
emitted as `fact_verification_completed`.

Events carry only safe operational metadata: `user_id`, `project_id`,
`source_id`, `job_id`, `output_id`, `overall_status`, and the bounded claim
counts. **No** claim text, evidence text, prompts, or source contents are ever
attached. Emission is fail-safe: an audit-sink failure is contained and never
changes the verification outcome or leaks to the user.

---

## Constraints

- Separate from the generation pipeline — fact verification never writes
  outputs, seeds, or ingestion artifacts.
- Bounded label cardinality in metrics — no claim text, source IDs, or UUIDs.
- The feature is user-triggered only (POST on demand); no automatic batch runs.
