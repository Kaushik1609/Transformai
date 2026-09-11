# TransformIQ — Consolidated Test Report (Phase 11I-3)

> Generated **2026-09-05** from live runner output for the specified commit.
> This report is additive documentation only — it changes no source code.

## 1. Summary

| Metric | Backend (pytest) | Frontend (jest) |
| --- | ---: | ---: |
| Total tests | 795 (794 pass + 1 skip) | 171 |
| Passed | 794 | 171 |
| Failed | 0 | 0 |
| Skipped | 1 | 0 |
| Test files / suites | 38 files | 25 suites |

- **Report generated against commit:** `af8a981` (`fix: single-source worker timeout, enforce DB failure write, bound embedding retry attempts`)
- Backend runner: `python -m pytest -v -rs --tb=no` → `794 passed, 1 skipped, 76 warnings in 51.95s`
- Frontend runner: `npx jest --json --silent` (CI=1) → `Test Suites: 25 passed, 25 total · Tests: 171 passed, 171 total · Snapshots: 0 total · Time: 6.941 s`
- Warnings on the backend run are `DeprecationWarning`/`PytestDeprecationWarning` noise from third-party libs (pytest-asyncio loop-scope default, `jose` `datetime.utcnow()`, `rq` string `on_failure` Callback deprecation) — none indicate a test failure.

## 2. Backend coverage by phase

Counts are exact per-file pass totals from the runner output. Files without a phase number (`test_config`, `test_health`, `test_gemini_provider`) are foundational and listed under *Pre-Phase 1*.

| Phase | Test file(s) | Passed |
| --- | --- | ---: |
| Pre-Phase 1 (foundation) | `test_config.py`, `test_health.py`, `test_gemini_provider.py` | 43 |
| Phase 1 (worker/connectivity) | `test_phase1_worker.py`, `test_phase1_connectivity.py` | 16 |
| Phase 2 (database API) | `test_phase2_database_api.py` | 69 |
| Phase 3A (ingestion foundation) | `test_phase3a_ingestion_foundation.py` | 18 |
| Phase 3B (source ingestion) | `test_phase3b_source_ingestion.py` | 9 |
| Phase 3C (document ingestion) | `test_phase3c_document_ingestion.py` | 9 |
| Phase 3D (ingestion worker + queue) | `test_phase3d_ingestion_worker.py`, `test_phase3d_ingestion_queue.py` | 7 |
| Phase 3E (embedding) | `test_phase3e_embedding.py` | 4 |
| Phase 3F (retrieval) | `test_phase3f_retrieval.py` | 8 |
| Phase 4 (content intelligence) | `test_phase4_content_intelligence.py` | 3 |
| Phase 5 (RAG) | `test_phase5_rag.py` | 10 |
| Phase 6 (transformation engine) | `test_phase6_transformation_engine.py` | 23 |
| Phase 7 (output generators + schema fix) | `test_phase7_output_generators.py`, `test_phase7_linkedin_x_schema_fix.py` | 46 |
| Phase 7D (LLM provider config) | `test_phase7d_llm_provider_config.py` | 14 |
| Phase 8 (verification engine) | `test_phase8_verification_engine.py` | 31 |
| Phase 8A (PPTX renderer) | `test_phase8a_pptx_renderer.py` | 13 |
| Phase 8B (DOCX + PDF renderers) | `test_phase8b_docx_renderer.py`, `test_phase8b_pdf_renderer.py` | 29 |
| Phase 8C (infographic renderer) | `test_phase8c_infographic_renderer.py` | 21 |
| Phase 8D (video renderer) | `test_phase8d_video_renderer.py` | 26 |
| Phase 8E (artifact download) | `test_phase8e_artifact_download.py` | 25 |
| Phase 9 (authorization) | `test_phase9a_authorization.py` | 37 |
| Phase 10A (output history) | `test_phase10a_output_history.py` | 7 |
| Phase 10B (output export) | `test_phase10b_output_export.py` | 14 |
| Phase 11 (RAG hardening) | `test_phase11_rag_hardening.py` | 22 |
| Phase 11C (orchestration) | `test_phase11c_orchestration.py` | 41 |
| Phase 11D (provider resilience) | `test_phase11d_provider_resilience.py` | 54 |
| Phase 11E (generation pipeline) | `test_phase11e_generation_pipeline.py` | 32 |
| Phase 11F (auth) | `test_phase11f_auth.py` | 45 |
| Phase 11G (embeddings & RAG quality) | `test_phase11g_embeddings.py` | 42 (+1 skipped) |
| Phase 11H (output security) | `test_phase11h_output_security.py` | 62 |
| Phase 11I-2 (worker timeout + retry bound) | `test_retry_amplification_bound.py`, `test_worker_timeout_enforcement.py` | 14 |
| **Total** | 38 files | **794** |

## 3. Frontend coverage by suite

Pass counts are per-suite from the jest JSON runner output (25 suites). Phase 11I-1 security suites are listed first.

### 11I-1 security suites

| Suite | File | Passed |
| --- | --- | ---: |
| Auth | `auth.test.tsx` | 11 |
| Require-auth token (token-gated dev bypass) | `require-auth-token.test.tsx` | 7 |
| History page | `history-page.test.tsx` | 3 |
| Projects page | `projects-page.test.tsx` | 6 |
| XSS escaping | `xss-escaping.test.tsx` | 4 |

### Remaining suites

| Suite | File | Passed |
| --- | --- | ---: |
| API domain | `api-domain.test.ts` | 16 |
| API download | `api-download.test.ts` | 6 |
| API phase 10 | `api-phase10.test.ts` | 10 |
| API | `api.test.ts` | 14 |
| Configuration form | `configuration-form.test.tsx` | 4 |
| Copy button | `copy-button.test.tsx` | 2 |
| Download button | `download-button.test.tsx` | 8 |
| Export button | `export-button.test.tsx` | 3 |
| History panel | `history-panel.test.tsx` | 8 |
| Home workspace | `home-workspace.test.tsx` | 2 |
| Output selector | `output-selector.test.tsx` | 4 |
| Output types | `outputTypes.test.ts` | 12 |
| Partial success | `partial-success.test.tsx` | 9 |
| Quick workspace | `quick-workspace.test.ts` | 2 |
| Results panel | `results-panel.test.tsx` | 9 |
| Source upload | `source-upload.test.tsx` | 7 |
| usePolling | `usePolling.test.tsx` | 6 |
| Utils | `utils.test.ts` | 8 |
| Verification panel | `verification-panel.test.tsx` | 4 |
| Workspace | `workspace.test.tsx` | 6 |
| **Total** | 25 suites | **171** |

## 4. Known skipped tests

| Test | File | Skip reason | Treated as |
| --- | --- | --- | --- |
| Real OpenAI embedding smoke test | `test_phase11g_embeddings.py:836` | `@pytest.mark.skipif(not os.environ.get("EMBEDDING_API_KEY"))` — "Real OpenAI embedding smoke test not run because credentials are unavailable." | Expected skip: opt-in live-provider check, disabled by default. Not a failure. |

This is the **only** skip in the combined run (backend `1 skipped`, frontend `0`). It is pre-existing (introduced in Phase 11G) and independent of Phase 11I-1/11I-2/11I-3.

## 5. Security & reliability coverage map

Cross-reference of the six defense layers to the test files that cover them.

| Layer | Scope | Coverage (test files) |
| --- | --- | --- |
| **L1 — Auth** | Authentication & authorization: OTP login/register, JWT issuance/validation, token-gated dev bypass, per-user object scoping, rate limiting | Backend: `test_phase11f_auth.py`, `test_phase9a_authorization.py`. Frontend: `auth.test.tsx`, `require-auth-token.test.tsx`, `projects-page.test.tsx`, `history-page.test.tsx`. Config: `DEV_AUTH_BYPASS` fail-closed validator in `test_config.py`. |
| **L2 — Ingestion** | Source ingestion pipeline: validation, storage, extraction, queue dispatch, embedding generation, retrieval indexing | `test_phase3a_ingestion_foundation.py`, `test_phase3b_source_ingestion.py`, `test_phase3c_document_ingestion.py`, `test_phase3d_ingestion_worker.py`, `test_phase3d_ingestion_queue.py`, `test_phase3e_embedding.py`, `test_phase3f_retrieval.py`. Worker timeout single-sourcing: `test_worker_timeout_enforcement.py`. |
| **L3 — Content** | Content intelligence & RAG retrieval: canonical analysis, retrieval scope enforcement (fail closed), RAG context limits | `test_phase4_content_intelligence.py`, `test_phase5_rag.py`, `test_phase11_rag_hardening.py`, plus 11G retrieval scope tests in `test_phase11g_embeddings.py`. |
| **L4 — Isolation** | Transformation orchestration isolation: per-output savepoints, partial success, sibling isolation, execution budget, retry/backoff bounds | `test_phase6_transformation_engine.py`, `test_phase11c_orchestration.py`, `test_phase11d_provider_resilience.py`, `test_phase11e_generation_pipeline.py`, `test_retry_amplification_bound.py`. Frontend: `partial-success.test.tsx`. |
| **L5 — Output** | Verified output generation & security: generators/renderers, verification engine, output sanitization (HTML/JS injection), artifact exports | `test_phase7_output_generators.py`, `test_phase7_linkedin_x_schema_fix.py`, `test_phase8_verification_engine.py`, `test_phase8a..test_phase8e` renderers, `test_phase10a_output_history.py`, `test_phase10b_output_export.py`, `test_phase11h_output_security.py`. Frontend: `xss-escaping.test.tsx`. |
| **L6 — Audit** | Traceable history & security metadata: output history retention, per-job security metadata persistence, failure-reason records, terminal-state writes | `test_phase10a_output_history.py`, `test_phase11h_output_security.py` (`test_sqlite_persistence_of_security_metadata`), `test_phase11f_auth.py` (OTP-attempt tracking), `test_worker_timeout_enforcement.py` (failed-status + timeout-reason DB write, no stuck `running`/`queued` states). |

This map is the value-add of this document: each layer has dedicated, passing coverage; no layer relies solely on incidental tests.