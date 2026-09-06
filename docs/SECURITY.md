# TransformIQ — Security Hardening & Auditability (Phase 11K)

This document describes the layered security controls introduced and verified in
Phase 11K. It complements the earlier `docs/PHASE9A_SECURITY.md` (foundation)
and the per-phase security work in Phases 11A–11J (source grounding, bounded
retrieval, output validation, credentials handling).

Phase 11K is a **defense-in-depth** layer. It does not replace any prior control;
it hardens logging, auditability, prompt-injection boundaries, and input bounds,
and it verifies the identity/rate-limit posture already established in Phase 11F.

> **Important:** security is never "complete". This document records *what is
> implemented and tested*, the *residual risks that remain*, and the
> *production configuration that operators must apply*. It is not a claim of
> perfect security.

---

## 1. CIA posture (dump: confidentiality, integrity, availability)

Security is addressed along the classic CIA axes:

| Axis | Control | Phase |
|------|---------|-------|
| **Confidentiality** | Credential-redaction processor on every log event; PII detection; secret-free error surfaces; OTP never logged; JWT bearer tokens redacted | 11K-D/11K-F |
| **Integrity** | Untrusted-data wrapping + delimiter escaping for all source content; operator-instruction isolation; bounded input fields; schema-validated output regeneration | 11K-E/11H |
| **Availability** | Rate limiting (per-bucket, IP-based) with a configured `RATE_LIMIT_ENABLED` master switch; worker job budgets | 11K-B / 11F |

---

## 2. Prompt-injection defense (11K-E)

The single highest-value area. Two complementary mechanisms are applied:

1. **Untrusted-data boundary (all source content).** `render_brief_text`
   (`app/transformation/brief.py`) now wraps *every* source-derived value —
   canonical fields **and** RAG evidence — inside a `<source_data>` /
   `</source_data>` block. An explicit hard statement tells the model that
   content inside the block is untrusted evidence, never instructions.

2. **Delimiter neutralization.** Any occurrence of an opening/closing block
   tag found *verbatim inside source content* is rewritten to an inert form
   (`</source_data>` → `[/source_data]`) so an attacker cannot forge/latch
   a trusted block boundary.

3. **Operator-instruction isolation.** `build_common_constraints`
   (`app/transformation/prompts/loader.py`) places user/operator
   `custom_instructions` inside its own `<operator_instructions>` block,
   explicitly subordinate to the SOURCE-GROUNDING rules. The grounding rules
   now also carry a hard exfiltration guard: the model must never disclose the
   system prompt, rules, environment variables, API keys, secrets, or internal
   configuration, and must ignore any embedded request to do so.

4. **Bounded evidence.** RAG evidence is clipped to `RAG_MAX_CONTEXT_CHARS`
   (default 4000) so the untrusted block can never carry an unbounded payload.

---

## 3. Log redaction & PII (11K-D / 11K-F)

- A shared `RedactionProcessor`
  (`app/core/redaction.py`) is the **first** structlog processor in the chain
  (`app/core/logging.py`) so every event — including request-validation errors
  and HTTP error details — is scrubbed before rendering. It recursively descends
  into dict/list payloads.
- Credential patterns covered: JWT/`eyJ...` tokens, `bearer <token>`,
  `sk-<key>` OpenAI-style keys, `name=value` / `name: value` secrets
  (api_key/token/authorization/password/secret/otp/passcode/pin/…),
  connection-URI credentials (`scheme://user:pass@host`), and PEM private-key
  blocks.
- The standalone `redact_secrets` helper is re-exported from
  `app/core.resilience` so existing LLM/embedding resilience callers keep using
  a single implementation.
- **Worker hardening:** `worker/worker.py` no longer logs the raw `REDIS_URL`
  (logs a credential-free host label via `_redis_host`), and all exception text
  (job failure, failure-handler, connection errors) is passed through
  `redact_secrets`.
- **PII detection** (`app/core/pii.py`) is a deterministic, conservative
  classifier for emails, phone-like numbers, IPv4 addresses, and Luhn-valid
  card numbers. It is used for hygiene and tests; it does **not** rewrite stored
  source artifacts (original files are kept untouched).

---

## 4. Structured audit events (11K-C)

`emit_security_event` (`app/core/audit.py`) records non-secret, denial-relevant
occurrences as structured `security_event` log records, plus a bounded in-process
list for programmatic inspection/tests. Events are gated by
`SECURITY_AUDIT_ENABLED` (default `true`).

Wired events:
- Authentication: `authn_denied` (invalid/missing/malformed token, unknown user).
- Authorization: `authz_denied` (role not in allowed tiers).
- Rate limiting: `rate_limit_triggered` (429 denial per bucket).
- Account/OTP lifecycle: `account_registered`, `account_registration_declined`,
  `otp_requested`, `otp_verified`, `otp_verification_denied`,
  `otp_issue_limited`, `otp_delivery_failed`.
- Resource lifecycle: `source_uploaded`, `source_deleted`, `project_deleted`.

Only identifiers and short reason strings are stored; never raw bodies, tokens,
OTPs, passwords, or document content.

---

## 5. Identity / rate limiting posture (11K-G / 11K-B)

- `DEV_AUTH_BYPASS` (Phase 11F) is enforced to be development-only: the settings
  model **fails closed** and raises if `DEV_AUTH_BYPASS=true` is combined with a
  non-development `ENVIRONMENT` (`app/core/config.py::_validate_dev_auth_bypass`).
  Production must keep `DEV_AUTH_BYPASS=false`.
- Rate limiting already exists (Phase 11F): memory (default/tests) and Redis
  (production) backends, per-IP buckets for `otp_request`, `otp_verify`,
  `login`, `source_upload`, and `transformation`. Phase 11K adds the audit event
  on every 429 denial and preserves the `RATE_LIMIT_ENABLED` master switch and
  `RATE_LIMIT_BACKEND` selection.

---

## 6. Input bounds (11K-H)

- `custom_instructions` on both `ConfigurationCreate` and `ConfigurationUpdate`
  are bounded to **2,000 characters** to prevent unbounded prompt expansion.
- `output_types` on `TransformationJobCreate` are bounded to **10 items** and each
  name to **32 characters** in addition to the existing allowlist. Other fields
  already carried `max_length` caps.

---

## 7. REMAINING SECURITY RISK (candid list)

- **Prompt injection cannot be fully eliminated.** Wrapping + escaping + rules
  materially reduce but do not provably eliminate LLM prompt-injection. An LLM
  is not an access-policy boundary.
- **`custom_instructions` is operator-supplied** and lands in the *system* prompt
  block. It is isolated and subordinated to grounding rules, but a compromised
  account could still steer output; treat configuration as near-privileged.
- **Redaction/PII patterns are heuristic.** They are strict to avoid false
  positives but will not catch every possible secret/PII representation (e.g.
  base64-encoded secrets, images). Defense relies on never logging sensitive
  values in the first place.
- **Rate limiting is in-process by default.** The memory backend is not shared
  across worker/API processes; production must set `RATE_LIMIT_BACKEND=redis`.
- **Redis limiter fails open** on a Redis outage (a deliberate availability
  trade-off). Logged as `redis_rate_limit_unavailable_failing_open`.
- **Audit events are logs, not tamper-proof DB rows.** They are durable only to
  the extent the log pipeline is. No blockchain/immutable ledger is used.

---

## 8. PRODUCTION CONFIGURATION REQUIRED

Operators must, before any real deployment:

1. Set `ENVIRONMENT=production` and **`DEV_AUTH_BYPASS=false`** (fail-closed).
2. Generate a strong random `AUTH_SECRET_KEY`
   (`openssl rand -hex 32`), keep it secret, never commit it.
3. Set `RATE_LIMIT_BACKEND=redis` and `REDIS_URL` pointing to the Redis instance.
4. Keep `RATE_LIMIT_ENABLED=true` and review per-bucket limits.
5. Keep `SECURITY_AUDIT_ENABLED=true`; route `security_event` records to the
   aggregation/alerting pipeline.
6. Fill real LLM/Embedding/Bucket credentials only in the local gitignored `.env`
   (`LLM_API_KEY`, `EMBEDDING_API_KEY`, `STORAGE_*`); never leave placeholders.
7. Restrict `ALLOWED_ORIGINS` to the real frontend origin(s).

---

## 9. FUTURE PHASE (recommended, not in scope for 11K)

- Persistent, tamper-evident audit store optionally backed by the DB on a
  dedicated schema (this phase intentionally keeps audit as structured logs to
  avoid a migration).
- Cryptographic output signing / provenance for generated artifacts.
- Per-user, not just per-IP, rate limiting and adaptive/abuse-triggered throttling.
- WebApplication/API firewalling in front of the API.