# TransformIQ — Production Configuration Matrix (Phase 11L-F)

Every configuration knob must be explicit in production: set from the platform
(no value is optional beyond the documented safe default), never supplied by a
client, and — for anything sensitive — injected via environment or secret
store, never committed. This matrix is the authoritative checklist.

Legend for **Validate?**:
`Y` — a wrong value runs in a degraded/unsafe but non-crashing state without
explicit validation; `M` — validated at boot by the application; `—` — no
validation required (used by other components, not the backend runtime).

## Component matrix

| Component | Current local default | Production requirement | Env var | Secret? | Validate? |
| --- | --- | --- | --- | --- | --- |
| **LLM** | `openai`/`gemini` (dev key) | Real provider + model; never fake | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` | Key: Y | —/M |
| **Embeddings** | `fake` | Real provider (`openai`); fake NEVER silently used in prod | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_DIMENSIONS` | Key: Y | M |
| **PostgreSQL** | Local docker | Managed/hardened Postgres; TLS; least-privilege role | `DATABASE_URL`, `DATABASE_SYNC_URL` | Y | M |
| **Redis** | Local docker | Shared Redis (queues, rate-limit, cache, worker metrics); TLS + auth | `REDIS_URL` | Y | M |
| **Storage** | `local` filesystem | Object storage (S3-compatible); bucket per environment; credentials least-privilege | `STORAGE_BACKEND`, `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_BUCKET`, `STORAGE_REGION`, `STORAGE_LOCAL_PATH` | Keys: Y | M |
| **Email (OTP)** | `console` provider | Real SMTP (or OTP SMS) provider, else OTP delivery fails silently in prod | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_FROM_NAME`, `OTP_PROVIDER` | Password: Y | — |
| **Auth secret** | `dev-secret-replace-before-production` (startup warns) | Strong random secret (>=32 bytes); rotate via key management; never default | `AUTH_SECRET_KEY` | Y | M |
| **Auth bypass** | `DEV_AUTH_BYPASS=false` | MUST be `false` | `DEV_AUTH_BYPASS` | — | M |
| **Rate limiting** | `redis` backend, per-bucket limits | Keep enabled; per-bucket limits per policy; Redis-backed for multi-instance | `RATE_LIMIT_ENABLED`, `RATE_LIMIT_BACKEND`, `RATE_LIMIT_*_MAX`, `RATE_LIMIT_*_WINDOW` | — | M |
| **Security audit** | `true` | Keep enabled; ship events to the audit store | `SECURITY_AUDIT_ENABLED` | — | — |
| **LLM output cache (new, 11L-A)** | Disabled | Enable with `redis` backend in prod for repeated-source cost savings | `CACHE_ENABLED`, `CACHE_BACKEND`, `CACHE_TTL_SECONDS`, `CACHE_KEY_VERSION` | — | M |
| **Worker processes (new, 11L-D)** | `WORKER_COUNT=1` | Scale worker replica count / `WORKER_COUNT` to demand; per-job timeout above LLM request budget | `WORKER_COUNT`, `WORKER_JOB_TIMEOUT` | — | M |
| **Job budget** | `TRANSFORMATION_JOB_TIMEOUT=600` | Must be ≤ `WORKER_JOB_TIMEOUT` (validated) and > `LLM_TIMEOUT_SECONDS` | `TRANSFORMATION_JOB_TIMEOUT` | — | M |
| **CORS / origins** | localhost frontend | Exact production origin(s); never `*` with credentials | `ALLOWED_ORIGINS` | — | — |
| **Frontend API URL** | `http://localhost:8000` (dev env file) | Public HTTPS API origin | frontend `NEXT_PUBLIC_API_URL`-style build env | — | — |
| **App environment** | `development` | `production` (structured JSON logs, dev rendering disabled) | `ENVIRONMENT` | — | — |

## Rules enforced by the application (do not soften)

1. **Fake providers are test-only.** The `fake` embedding provider exists for
   offline tests; a real provider selected in `EMBEDDING_PROVIDER` never falls
   back to fake on credential failure — it fails the job loudly (Phase 11G).
2. **Timeout hierarchy** (`_validate_worker_job_timeout`): worker timeout ≥ job
   budget > LLM provider timeout. Violations fail at boot.
3. **Cache is disabled by default.** `CACHE_ENABLED` must be set explicitly to
   `true` in production; without it, every transformation pays the full LLM
   cost. `CACHE_BACKEND=redis` is required for multi-instance deployments
   (`memory` is per-process).
4. **Worker scaling is process count.** An RQ 2.0 worker executes one job at a
   time; `WORKER_COUNT` (new) launches that many worker processes on the shared
   queues. The legacy `WORKER_CONCURRENCY` knob was never wired to RQ behavior
   and is **no longer read anywhere** in the codebase — do not rely on it.
   (The architecture docs at `ARCHITECTURE.md`/`docs/ARCHITECTURE.md` still
   mention it; they are documentation-only and the correction is recorded here.)
5. **Metrics never expose identities.** `/metrics` is intentionally
   unauthenticated (like `/health`). Labels are bounded to method/route/status/
   output-type/provider; user, project and job IDs are never emitted.

## Boot-time validation

The backend validates the following at startup (pydantic validators — a bad
value crashes the process fast rather than running degraded):

- `WORKER_COUNT` in `[1, 128]`
- `CACHE_TTL_SECONDS` in `[60, 604800]`
- `CACHE_BACKEND` in `{memory, redis}`
- `TRANSFORMATION_JOB_TIMEOUT ≤ WORKER_JOB_TIMEOUT`
- buffer/upload and bounded security-limit fields

## Required production secret inventory

Set these ONLY from the deployment platform / secret manager (never via a
committed `.env`): `LLM_API_KEY`, `EMBEDDING_API_KEY`, `AUTH_SECRET_KEY`,
`DATABASE_URL`/`DATABASE_SYNC_URL` credentials, `REDIS_URL` credentials,
`STORAGE_ACCESS_KEY`/`STORAGE_SECRET_KEY`, `SMTP_PASSWORD` (and SMS tokens if
used).