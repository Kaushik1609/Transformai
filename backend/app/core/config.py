"""
TransformIQ Backend — Application Configuration

All configuration is read from environment variables.
Never hard-code secrets or credentials here.
"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _positive_bounded(value: int, name: str, upper: int) -> int:
    """Validate that a configuration value is a bounded positive integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    if value > upper:
        raise ValueError(f"{name} must not exceed {upper}.")
    return value


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All fields with sensitive values (API keys, passwords, secrets) must be
    supplied through the environment or a .env file. They must NEVER be
    committed to Git.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # Development-only auth bypass.
    # When True a placeholder user identity is injected so the API is usable
    # without a real authentication token.
    # MUST be False in staging and production.
    DEV_AUTH_BYPASS: bool = False

    # Structured security/audit event emitter (Phase 11K). When False the
    # emitter records nothing and logs no security_event records.
    SECURITY_AUDIT_ENABLED: bool = True

    # Audit sink: "memory" keeps the historical bounded in-process store
    # (Phase 11K behavior) served by the security-events API; "database"
    # additionally/persistently drains events into the `security_events` table
    # (Phase 13D) and the security-events API reads from the database. The
    # database sink requires migrations to have been applied (alembic head).
    SECURITY_AUDIT_SINK: Literal["memory", "database"] = "memory"

    # Max in-process audit records retained for inspection (bounded memory).
    SECURITY_AUDIT_MEMORY_MAX_EVENTS: int = 5000

    # -------------------------------------------------------------------------
    # Backend
    # -------------------------------------------------------------------------
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------


    DATABASE_URL: str = (
        "postgresql+asyncpg://transformiq:changeme@localhost:5432/transformiq"
    )
    DATABASE_SYNC_URL: str = (
        "postgresql://transformiq:changeme@localhost:5432/transformiq"
    )

    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"

    @field_validator("REDIS_URL")
    @classmethod
    def normalize_redis_url(cls, v: str) -> str:
        """Cloud Redis providers like Upstash require TLS (rediss://)."""
        if "upstash.io" in v and v.startswith("redis://"):
            return "rediss://" + v[len("redis://") :]
        return v

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    AUTH_SECRET_KEY: str = "dev-secret-replace-before-production"
    AUTH_ALGORITHM: str = "HS256"
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AUTH_TOKEN_TYPE: str = "bearer"

    # Server-side token revocation (Phase 13A). Every JWT carries a unique
    # ``jti`` claim; logout registers that ``jti`` in a revocation store so the
    # token cannot be replayed. memory = bounded in-process denylist (single
    # replica default); redis = shared denylist across replicas.
    AUTH_TOKEN_REVOCATION_STORE: Literal["memory", "redis"] = "memory"
    # Upper bound of distinct revoked tokens cached in the memory store
    # (bounded memory; expired entries are swept first).
    AUTH_REVOKED_TOKEN_MAX: int = 100_000

    # -------------------------------------------------------------------------
    # Auth (Phase 11F — L1 Perimeter & Identity)
    # -------------------------------------------------------------------------
    # Whether new account registration is allowed. Disable to go invite-only.
    REGISTRATION_ENABLED: bool = True
    # Token issuer / audience claims embedded in JWTs.
    AUTH_ISSUER: str = "transformiq"
    AUTH_AUDIENCE: str = "transformiq-api"

    # OTP issuance + verification policy.
    OTP_LENGTH: int = 6
    OTP_EXPIRY_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_ISSUES_PER_WINDOW: int = 10
    OTP_ISSUE_WINDOW_SECONDS: int = 900

    # OTP storage / delivery backends (memory = offline/tests; redis = prod).
    OTP_STORE_BACKEND: Literal["memory", "redis"] = "memory"
    OTP_PROVIDER: Literal["console", "email", "sms"] = "console"

    # Email delivery (OTP_PROVIDER=email). Never hard-code credentials.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "TransformIQ"

    # SMS delivery (OTP_PROVIDER=sms). Never hard-code credentials.
    SMS_ACCOUNT_SID: str = ""
    SMS_AUTH_TOKEN: str = ""
    SMS_FROM: str = ""

    # -------------------------------------------------------------------------
    # Rate limiting (Phase 11F — shared Redis-infrastructure, memory fallback)
    # -------------------------------------------------------------------------
    RATE_LIMIT_BACKEND: Literal["memory", "redis"] = "memory"
    # Master switch. When False every rate-limit dependency permits requests.
    RATE_LIMIT_ENABLED: bool = True
    # Upper bound of distinct (bucket, key) tracks kept by the in-process
    # limiter. Exceeding this evicts the oldest tracks (bounded memory).
    RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS: int = 100_000
    # (limit, window_seconds) buckets.
    RATE_LIMIT_OTP_REQUEST_MAX: int = 10
    RATE_LIMIT_OTP_REQUEST_WINDOW: int = 900
    RATE_LIMIT_OTP_VERIFY_MAX: int = 10
    RATE_LIMIT_OTP_VERIFY_WINDOW: int = 300
    RATE_LIMIT_LOGIN_MAX: int = 10
    RATE_LIMIT_LOGIN_WINDOW: int = 900
    RATE_LIMIT_SOURCE_UPLOAD_MAX: int = 100
    RATE_LIMIT_SOURCE_UPLOAD_WINDOW: int = 3600
    RATE_LIMIT_TRANSFORMATION_MAX: int = 100
    RATE_LIMIT_TRANSFORMATION_WINDOW: int = 3600

    @field_validator("AUTH_SECRET_KEY")
    @classmethod
    def warn_default_secret(cls, v: str) -> str:
        if v == "dev-secret-replace-before-production":
            import warnings

            warnings.warn(
                "AUTH_SECRET_KEY is using the default development value. "
                "Set a strong random secret before deploying.",
                stacklevel=2,
            )
        return v

    # -------------------------------------------------------------------------
    # LLM Provider (provider-agnostic, configured via env)
    # -------------------------------------------------------------------------
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    # Optional base URL for OpenAI-compatible endpoints (e.g. a gateway or
    # self-hosted provider). When empty, the OpenAI provider uses its default
    # endpoint, preserving existing behavior. Intended for development/prototype
    # testing only; do not make a third-party gateway the permanent default.
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 60

    # -------------------------------------------------------------------------
    # LLM resilience (Phase 11D)
    # -------------------------------------------------------------------------
    # Disable SDK-internal automatic retries so the application ProviderManager
    # is the SINGLE retry owner (avoids nested/amplified retry pressure).
    LLM_SDK_MAX_RETRIES: int = 0
    # Total provider attempts allowed per generation call (retries occur within
    # this budget; no sleep after the final attempt).
    LLM_RETRY_MAX_ATTEMPTS: int = 3
    # Exponential backoff: delay = base * 2^attempt, clamped to max and jittered.
    LLM_RETRY_BASE_DELAY: float = 0.5
    LLM_RETRY_MAX_DELAY: float = 10.0
    # Jitter fraction (0..1) applied to the computed delay before sleeping.
    LLM_RETRY_JITTER: float = 0.2
    # Clamp for Retry-After values honoring by the 429 handling.
    LLM_RETRY_MAX_429_WAIT: float = 30.0
    # Optional fallback provider name ("fake", "openai", or blank for none).
    # Fallback is only used when configured; never required.
    LLM_FALLBACK_PROVIDER: str = ""

    # -------------------------------------------------------------------------
    # Embedding
    # -------------------------------------------------------------------------
    # Supported providers: "fake" (deterministic, offline/tests) and "openai"
    # (real embeddings via the OpenAI SDK). Never hard-code keys here.
    EMBEDDING_PROVIDER: Literal["fake", "openai"] = "fake"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    # Real-provider credentials/base URL (EMBEDDING_PROVIDER=openai). The key is
    # consumed from the local gitignored .env only and never committed/printed.
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = ""
    # Per-request network timeout and max retries for real providers. The total
    # request budget (timeout * (retries + 1)) is validated below so it can never
    # exceed the worker's execution budget.
    EMBEDDING_TIMEOUT_SECONDS: int = 10
    EMBEDDING_MAX_RETRIES: int = 2
    # Disable SDK-internal automatic retries so the application
    # EmbeddingResilientProvider is the SINGLE retry owner (avoids nested/amplified
    # retry pressure). EMBEDDING_MAX_TOTAL_ATTEMPTS below is the one documented
    # ceiling for the whole embedding retry stack.
    EMBEDDING_SDK_MAX_RETRIES: int = 0

    @property
    def EMBEDDING_MAX_TOTAL_ATTEMPTS(self) -> int:
        """Single documented retry ceiling for the embedding stack.

        The EmbeddingResilientProvider may attempt a request at most this many
        times (EMBEDDING_MAX_RETRIES retries plus the initial attempt). Because
        EMBEDDING_SDK_MAX_RETRIES is 0, this is the ONLY retry layer that can
        exceed one attempt and therefore the ONLY ceiling.
        """
        return self.EMBEDDING_MAX_RETRIES + 1

    @field_validator("EMBEDDING_DIMENSIONS")
    @classmethod
    def validate_embedding_dimensions(cls, v: int) -> int:
        """Vector dimensionality must be positive; 1536 matches the pgvector column."""
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be a positive integer.")
        return v

    @field_validator("EMBEDDING_TIMEOUT_SECONDS")
    @classmethod
    def validate_embedding_timeout(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError("EMBEDDING_TIMEOUT_SECONDS must be a positive integer.")
        return v

    @field_validator("EMBEDDING_MAX_RETRIES")
    @classmethod
    def validate_embedding_max_retries(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10:
            raise ValueError("EMBEDDING_MAX_RETRIES must be an integer in [0, 10].")
        return v

    @field_validator("EMBEDDING_SDK_MAX_RETRIES")
    @classmethod
    def validate_embedding_sdk_max_retries(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10:
            raise ValueError("EMBEDDING_SDK_MAX_RETRIES must be an integer in [0, 10].")
        return v

    # -------------------------------------------------------------------------
    # RAG / Retrieval
    # -------------------------------------------------------------------------
    RAG_TOP_K: int = 5
    RAG_MIN_SIMILARITY: float = 0.0
    RAG_MAX_CONTEXT_CHARS: int = 4000

    @field_validator("RAG_TOP_K")
    @classmethod
    def validate_rag_top_k(cls, v: int) -> int:
        """Prevent pathological/zero top_k values."""
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError("RAG_TOP_K must be a positive integer.")
        if v > 100:
            raise ValueError("RAG_TOP_K must not exceed 100.")
        return v

    @field_validator("RAG_MIN_SIMILARITY")
    @classmethod
    def validate_rag_min_similarity(cls, v: float) -> float:
        """Clamp the similarity threshold to the valid cosine-similarity range."""
        value = float(v)
        if value < 0.0 or value > 1.0:
            raise ValueError("RAG_MIN_SIMILARITY must be between 0.0 and 1.0.")
        return value

    @field_validator("RAG_MAX_CONTEXT_CHARS")
    @classmethod
    def validate_rag_max_context_chars(cls, v: int) -> int:
        """Bound the assembled context so it can never be unbounded."""
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError("RAG_MAX_CONTEXT_CHARS must be a positive integer.")
        if v > 100_000:
            raise ValueError("RAG_MAX_CONTEXT_CHARS must not exceed 100000.")
        return v

    @field_validator("LLM_SDK_MAX_RETRIES")
    @classmethod
    def validate_llm_sdk_max_retries(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10:
            raise ValueError("LLM_SDK_MAX_RETRIES must be an integer in [0, 10].")
        return v

    @field_validator("LLM_RETRY_MAX_ATTEMPTS")
    @classmethod
    def validate_llm_retry_max_attempts(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 20:
            raise ValueError("LLM_RETRY_MAX_ATTEMPTS must be an integer in [1, 20].")
        return v

    @field_validator("LLM_RETRY_BASE_DELAY")
    @classmethod
    def validate_llm_retry_base_delay(cls, v: float) -> float:
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise ValueError("LLM_RETRY_BASE_DELAY must be a non-negative number.")
        return float(v)

    @field_validator("LLM_RETRY_MAX_DELAY")
    @classmethod
    def validate_llm_retry_max_delay(cls, v: float) -> float:
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise ValueError("LLM_RETRY_MAX_DELAY must be a non-negative number.")
        return float(v)

    @field_validator("LLM_RETRY_JITTER")
    @classmethod
    def validate_llm_retry_jitter(cls, v: float) -> float:
        value = float(v)
        if value < 0.0 or value > 1.0:
            raise ValueError("LLM_RETRY_JITTER must be between 0.0 and 1.0.")
        return value

    @field_validator("LLM_RETRY_MAX_429_WAIT")
    @classmethod
    def validate_llm_retry_max_429_wait(cls, v: float) -> float:
        value = float(v)
        if value < 0.0:
            raise ValueError("LLM_RETRY_MAX_429_WAIT must be a non-negative number.")
        return value

    # -------------------------------------------------------------------------
    # L5 Output Security (Phase 11H)
    # -------------------------------------------------------------------------
    # Deterministic post-parse security validation of generated output
    # structures.  All limits are finite upper bounds; there are no unlimited
    # values.  Defaults are deliberately generous so legitimate model output is
    # never rejected (only pathological strings/list/counts are flagged).
    OUTPUT_SECURITY_ENABLED: bool = True
    OUTPUT_MAX_STRING_LENGTH: int = 20000
    OUTPUT_MAX_LIST_LENGTH: int = 500
    OUTPUT_MAX_NESTED_ITEMS: int = 1000
    OUTPUT_MAX_SLIDES: int = 100
    OUTPUT_MAX_VIDEO_SCENES: int = 100
    OUTPUT_MAX_INF_SECTIONS: int = 100
    OUTPUT_MAX_X_THREAD_ITEMS: int = 50
    # Number of re-generation attempts allowed when the model's output fails
    # SCHEMA validation (not provider failures, not verification warnings).
    # 0 = current behavior (a schema-invalid output simply fails that output).
    OUTPUT_REGEN_BUDGET: int = 0

    @field_validator("OUTPUT_MAX_STRING_LENGTH")
    @classmethod
    def validate_output_max_string_length(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_STRING_LENGTH", 1_000_000)

    @field_validator("OUTPUT_MAX_LIST_LENGTH")
    @classmethod
    def validate_output_max_list_length(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_LIST_LENGTH", 100_000)

    @field_validator("OUTPUT_MAX_NESTED_ITEMS")
    @classmethod
    def validate_output_max_nested_items(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_NESTED_ITEMS", 1_000_000)

    @field_validator("OUTPUT_MAX_SLIDES")
    @classmethod
    def validate_output_max_slides(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_SLIDES", 100_000)

    @field_validator("OUTPUT_MAX_VIDEO_SCENES")
    @classmethod
    def validate_output_max_video_scenes(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_VIDEO_SCENES", 100_000)

    @field_validator("OUTPUT_MAX_INF_SECTIONS")
    @classmethod
    def validate_output_max_inf_sections(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_INF_SECTIONS", 100_000)

    @field_validator("OUTPUT_MAX_X_THREAD_ITEMS")
    @classmethod
    def validate_output_max_x_thread_items(cls, v: int) -> int:
        return _positive_bounded(v, "OUTPUT_MAX_X_THREAD_ITEMS", 100_000)

    @field_validator("OUTPUT_REGEN_BUDGET")
    @classmethod
    def validate_output_regen_budget(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10:
            raise ValueError("OUTPUT_REGEN_BUDGET must be an integer in [0, 10].")
        return v

    # -------------------------------------------------------------------------
    # File Storage
    # -------------------------------------------------------------------------
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_PATH: str = "/app/storage"
    STORAGE_ENDPOINT: str = ""
    STORAGE_ACCESS_KEY: str = ""
    STORAGE_SECRET_KEY: str = ""
    STORAGE_BUCKET: str = "transformiq"
    STORAGE_REGION: str = "us-east-1"
    # S3-compatible path-style addressing (required by MinIO; AWS S3 auto-detects).
    STORAGE_PATH_STYLE: bool = True

    # -------------------------------------------------------------------------
    # Upload limits
    # -------------------------------------------------------------------------
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_UPLOAD_TYPES: str = (
        "application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "text/plain"
    )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # -------------------------------------------------------------------------
    # Ingestion resource limits (Phase 13E)
    # -------------------------------------------------------------------------
    # Bounded processing budgets so a single source file can never exhaust
    # worker time or memory. A document exceeding any cap is rejected with a
    # controlled ingestion failure (never truncated silently).
    MAX_PDF_PAGES: int = 500
    MAX_EXTRACTED_CHARS: int = 2_000_000
    # Direct-text source size cap (bytes).
    INPUT_MAX_TEXT_LENGTH: int = 500_000
    # Upper bound on chunks produced from one source.
    MAX_SOURCE_CHUNKS: int = 10_000

    # -------------------------------------------------------------------------
    # Malware scanning (Phase 12D-A)
    # -------------------------------------------------------------------------
    # Local-only source-file scanning. NO third-party upload services.
    # When enabled, uploaded bytes are scanned before persistence/extraction.
    # When REQUIRED, a scanned-but-unavailable scanner rejects ingestion
    # (fail-closed); a non-required scanner degrades to 'unavailable' metadata.
    MALWARE_SCAN_ENABLED: bool = False
    MALWARE_SCAN_REQUIRED: bool = False
    # Scanner backend: fake (offline/tests) | clamav (local clamd service).
    MALWARE_SCANNER: Literal["fake", "clamav"] = "fake"
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: int = 10

    @property
    def allowed_upload_types_list(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_UPLOAD_TYPES.split(",") if t.strip()]

    # -------------------------------------------------------------------------
    # Caching (Phase 11L-A)
    # -------------------------------------------------------------------------
    # Master switch. Disabled by default to preserve historical behavior and
    # test determinism; production configuration enables it.
    CACHE_ENABLED: bool = False
    # Backend: memory (offline/tests, bounded) | redis (shared, production).
    CACHE_BACKEND: Literal["memory", "redis"] = "memory"
    # Time-to-live for cached LLM outputs.
    CACHE_TTL_SECONDS: int = 3600
    # Version tag embedded in every cache key so a key-format change invalidates
    # old entries naturally (set to a new value to hard-expire all caches).
    CACHE_KEY_VERSION: str = "v1"
    # Number of worker PROCESSES to launch (a single RQ 2.0 worker runs one job
    # at a time, so scaling is process count, not threads). This replaces the
    # legacy WORKER_CONCURRENCY knob, which was never wired to any RQ behavior
    # and is no longer read anywhere.
    WORKER_COUNT: int = 1

    @field_validator("CACHE_TTL_SECONDS")
    @classmethod
    def validate_cache_ttl(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 60 or v > 604800:
            raise ValueError("CACHE_TTL_SECONDS must be an integer in [60, 604800].")
        return v

    @field_validator("WORKER_COUNT")
    @classmethod
    def validate_worker_count(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 128:
            raise ValueError("WORKER_COUNT must be an integer in [1, 128].")
        return v

    # -------------------------------------------------------------------------
    # Artifact integrity / provenance (Phase 11M)
    # -------------------------------------------------------------------------
    # POST-GENERATION provenance layer. Recording a hash never blocks artifact
    # persistence (fail-open by default); verification is always read-only.
    # Ledger provider: fake (offline/tests) | real (configurable production
    # adapter) | none (integrity hashes + local verification only, no ledger).
    INTEGRITY_PROVIDER: Literal["fake", "real", "none"] = "fake"
    # If True, record an integrity ledger reference for every persisted artifact
    # during generation. If False, hashes already recorded by Phase 11H-I remain
    # in output_metadata but no ledger reference is written.
    INTEGRITY_RECORD_ENABLED: bool = True
    # Deterministic algorithm used for content hashing.
    INTEGRITY_ALGORITHM: Literal["sha256"] = "sha256"
    # Real-ledger network/target (PRODUCTION-CONFIGURATION-REQUIRED; never a
    # committed secret). Left empty -> the real adapter reports 'unavailable'
    # rather than pretending a write succeeded.
    INTEGRITY_LEDGER_URL: str = ""
    # Real-ledger credential reference (secret manager value only; never set to
    # a literal in any repo file).
    INTEGRITY_LEDGER_CREDENTIAL: str = ""

    # -------------------------------------------------------------------------
    # Evidence / fact verification (Phase 11N)
    # -------------------------------------------------------------------------
    # On-demand factual verification of generated outputs against project-scoped
    # source evidence. Purely additive to the Phase 8 verification pipeline; it
    # never runs inside the generation workflow. See
    # app/transformation/verification_engine/fact_verifier.py.
    FACT_VERIFICATION_ENABLED: bool = True
    # Upper bound on how many extracted claims are checked per request. Claim
    # extraction stays conservative (Phase 8 signals), but the count is capped
    # so a single response stays bounded.
    FACT_VERIFICATION_MAX_CLAIMS: int = 20
    # Number of source chunks retrieved per claim (top-k for the RAG-backed
    # evidence retrieval; reuses RAGService.retrieve_context_for_source).
    FACT_VERIFICATION_TOP_K: int = 3
    # Minimum cosine similarity for retrieved evidence (0.0 preserves legacy
    # behavior where every scoped chunk is a retrieval candidate).
    FACT_VERIFICATION_MIN_SIMILARITY: float = 0.0
    # Maximum number of retrieved citations surfaced per claim in the response.
    FACT_VERIFICATION_MAX_EVIDENCE_PER_CLAIM: int = 3

    # -------------------------------------------------------------------------
    # Worker
    # -------------------------------------------------------------------------
    # The RQ worker timeout is a final safety backstop for queue jobs and MUST be
    # greater than (or equal to) the per-transformation execution budget so the
    # worker never terminates a job before its application-level budget elapses.
    WORKER_JOB_TIMEOUT: int = 605
    # Per-transformation execution budget (seconds). This job budget must exceed
    # the per-provider request timeout (LLM_TIMEOUT_SECONDS) and MUST NOT exceed
    # WORKER_JOB_TIMEOUT (enforced by the validator below).
    TRANSFORMATION_JOB_TIMEOUT: int = 600
    # Stale-job grace period (Phase 13G). A transformation job stuck in the
    # ``running`` state for longer than this many seconds is assumed orphaned
    # (worker died/crashed mid-job) and failed by the backend reaper. Must be
    # strictly greater than WORKER_JOB_TIMEOUT so a live-but-slow job is never
    # touched (RQ already fails jobs that exceed WORKER_JOB_TIMEOUT).
    STALE_TRANSFORMATION_JOB_GRACE_SECONDS: int = 1200
    # Backend reaper sweep interval (Phase 13G). The reaper is an asyncio task
    # started in the API lifespan; disabling it leaves stale-job handling to RQ
    # timeouts alone.
    STALE_JOB_REAPER_ENABLED: bool = True
    STALE_JOB_REAPER_INTERVAL_SECONDS: int = 600

    @model_validator(mode="after")
    def _validate_worker_job_timeout(self) -> "Settings":
        """Preserve the timeout hierarchy: worker >= job budget.

        The worker's RQ hard timeout terminates a job if it exceeds the budget,
        so it must be at least as large as the per-transformation execution
        budget (which itself exceeds the per-provider request timeout).  This
        validator rejects a configuration that would let the worker kill a job
        before its own budget completes.
        """
        worker = self.WORKER_JOB_TIMEOUT
        budget = self.TRANSFORMATION_JOB_TIMEOUT
        if isinstance(worker, int) and isinstance(budget, int):
            if worker < budget:
                raise ValueError(
                    "WORKER_JOB_TIMEOUT must be >= TRANSFORMATION_JOB_TIMEOUT "
                    f"({worker} < {budget}); the worker would terminate "
                    "transformation jobs before their execution budget elapsed."
                )
        return self

    @model_validator(mode="after")
    def _validate_embedding_request_budget(self) -> "Settings":
        """Bound the embedding request budget inside the worker's execution budget.

        A real embedding request may take up to EMBEDDING_TIMEOUT_SECONDS and be
        retried EMBEDDING_MAX_RETRIES times, so the worst case is
        timeout * (retries + 1). This validator rejects a configuration that
        could let an embedding job exceed the worker's safe execution budget.
        """
        timeout = self.EMBEDDING_TIMEOUT_SECONDS
        retries = self.EMBEDDING_MAX_RETRIES
        if isinstance(timeout, int) and isinstance(retries, int):
            worst_case = timeout * (retries + 1)
            if worst_case > self.WORKER_JOB_TIMEOUT:
                raise ValueError(
                    "Embedding request budget "
                    f"(EMBEDDING_TIMEOUT_SECONDS * (EMBEDDING_MAX_RETRIES + 1) = {worst_case}s) "
                    f"would exceed WORKER_JOB_TIMEOUT={self.WORKER_JOB_TIMEOUT}s."
                )
        return self

    @model_validator(mode="after")
    def _validate_dev_auth_bypass(self) -> "Settings":
        """Fail closed: DEV_AUTH_BYPASS must never be enabled outside development.

        This makes it impossible for a staging/production configuration to
        silently expose the API without authentication.
        """
        if self.DEV_AUTH_BYPASS and self.ENVIRONMENT != "development":
            raise ValueError(
                "DEV_AUTH_BYPASS must be False when ENVIRONMENT is not "
                "'development'; refusing to run an unauthenticated API in "
                f"{self.ENVIRONMENT}."
            )
        return self

    @model_validator(mode="after")
    def _validate_otp_policy(self) -> "Settings":
        """Keep the OTP policy within sane security bounds."""
        if self.OTP_LENGTH < 6:
            raise ValueError("OTP_LENGTH must be at least 6.")
        if self.OTP_EXPIRY_SECONDS < 30 or self.OTP_EXPIRY_SECONDS > 1800:
            raise ValueError("OTP_EXPIRY_SECONDS must be between 30 and 1800.")
        if self.OTP_MAX_ATTEMPTS < 1 or self.OTP_MAX_ATTEMPTS > 20:
            raise ValueError("OTP_MAX_ATTEMPTS must be between 1 and 20.")
        if self.OTP_RESEND_COOLDOWN_SECONDS < 5:
            raise ValueError("OTP_RESEND_COOLDOWN_SECONDS must be at least 5s.")
        return self

    @model_validator(mode="after")
    def _validate_rate_limit_buckets(self) -> "Settings":
        """Reject degenerate rate-limit configurations (min 1 request / 1s)."""
        for name, limit, window in (
            ("RATE_LIMIT_OTP_REQUEST", self.RATE_LIMIT_OTP_REQUEST_MAX, self.RATE_LIMIT_OTP_REQUEST_WINDOW),
            ("RATE_LIMIT_OTP_VERIFY", self.RATE_LIMIT_OTP_VERIFY_MAX, self.RATE_LIMIT_OTP_VERIFY_WINDOW),
            ("RATE_LIMIT_LOGIN", self.RATE_LIMIT_LOGIN_MAX, self.RATE_LIMIT_LOGIN_WINDOW),
            ("RATE_LIMIT_SOURCE_UPLOAD", self.RATE_LIMIT_SOURCE_UPLOAD_MAX, self.RATE_LIMIT_SOURCE_UPLOAD_WINDOW),
            ("RATE_LIMIT_TRANSFORMATION", self.RATE_LIMIT_TRANSFORMATION_MAX, self.RATE_LIMIT_TRANSFORMATION_WINDOW),
        ):
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ValueError(f"{name}_MAX must be a positive integer (>= 1).")
            if not isinstance(window, int) or isinstance(window, bool) or window < 1:
                raise ValueError(f"{name}_WINDOW must be a positive integer (>= 1).")
        return self

    @model_validator(mode="after")
    def _validate_malware_scan(self) -> "Settings":
        """Enforce a coherent, fail-closed malware-scan configuration.

        A required scan that is disabled is a misconfiguration (a "required"
        protection that can never run).  The scanner never silently bypasses a
        required scan at scan time (see ingestion/malware_scan run helper).
        """
        if self.MALWARE_SCAN_REQUIRED and not self.MALWARE_SCAN_ENABLED:
            raise ValueError(
                "MALWARE_SCAN_REQUIRED must not be True when MALWARE_SCAN_ENABLED "
                "is False; a required scan can never run."
            )
        if (
            not isinstance(self.CLAMAV_PORT, int)
            or isinstance(self.CLAMAV_PORT, bool)
            or self.CLAMAV_PORT < 1
            or self.CLAMAV_PORT > 65535
        ):
            raise ValueError("CLAMAV_PORT must be an integer in [1, 65535].")
        if (
            not isinstance(self.CLAMAV_TIMEOUT_SECONDS, int)
            or isinstance(self.CLAMAV_TIMEOUT_SECONDS, bool)
            or self.CLAMAV_TIMEOUT_SECONDS < 1
            or self.CLAMAV_TIMEOUT_SECONDS > 300
        ):
            raise ValueError(
                "CLAMAV_TIMEOUT_SECONDS must be an integer in [1, 300]."
            )
        return self

    @model_validator(mode="after")
    def _validate_bounded_phase13_knobs(self) -> "Settings":
        """Reject degenerate Phase 13 bounded-resource configurations."""
        if (
            not isinstance(self.MAX_PDF_PAGES, int)
            or isinstance(self.MAX_PDF_PAGES, bool)
            or self.MAX_PDF_PAGES < 1
            or self.MAX_PDF_PAGES > 5000
        ):
            raise ValueError("MAX_PDF_PAGES must be an integer in [1, 5000].")
        if (
            not isinstance(self.MAX_EXTRACTED_CHARS, int)
            or isinstance(self.MAX_EXTRACTED_CHARS, bool)
            or self.MAX_EXTRACTED_CHARS < 1000
            or self.MAX_EXTRACTED_CHARS > 100_000_000
        ):
            raise ValueError(
                "MAX_EXTRACTED_CHARS must be an integer in [1000, 100000000]."
            )
        if (
            not isinstance(self.INPUT_MAX_TEXT_LENGTH, int)
            or isinstance(self.INPUT_MAX_TEXT_LENGTH, bool)
            or self.INPUT_MAX_TEXT_LENGTH < 1000
            or self.INPUT_MAX_TEXT_LENGTH > 50_000_000
        ):
            raise ValueError(
                "INPUT_MAX_TEXT_LENGTH must be an integer in [1000, 50000000]."
            )
        if (
            not isinstance(self.MAX_SOURCE_CHUNKS, int)
            or isinstance(self.MAX_SOURCE_CHUNKS, bool)
            or self.MAX_SOURCE_CHUNKS < 1
            or self.MAX_SOURCE_CHUNKS > 1_000_000
        ):
            raise ValueError(
                "MAX_SOURCE_CHUNKS must be an integer in [1, 1000000]."
            )
        return self

    @model_validator(mode="after")
    def _validate_revocation_and_grace(self) -> "Settings":
        """Bound revocation memory and keep grace above the worker timeout."""
        if (
            not isinstance(self.AUTH_REVOKED_TOKEN_MAX, int)
            or isinstance(self.AUTH_REVOKED_TOKEN_MAX, bool)
            or self.AUTH_REVOKED_TOKEN_MAX < 1000
            or self.AUTH_REVOKED_TOKEN_MAX > 10_000_000
        ):
            raise ValueError(
                "AUTH_REVOKED_TOKEN_MAX must be an integer in [1000, 10000000]."
            )
        if (
            not isinstance(self.RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS, int)
            or isinstance(self.RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS, bool)
            or self.RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS < 100
            or self.RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS > 10_000_000
        ):
            raise ValueError(
                "RATE_LIMIT_MEMORY_MAX_TRACKED_KEYS must be an integer in "
                "[100, 10000000]."
            )
        if (
            not isinstance(self.SECURITY_AUDIT_MEMORY_MAX_EVENTS, int)
            or isinstance(self.SECURITY_AUDIT_MEMORY_MAX_EVENTS, bool)
            or self.SECURITY_AUDIT_MEMORY_MAX_EVENTS < 100
            or self.SECURITY_AUDIT_MEMORY_MAX_EVENTS > 1_000_000
        ):
            raise ValueError(
                "SECURITY_AUDIT_MEMORY_MAX_EVENTS must be an integer in "
                "[100, 1000000]."
            )
        if self.STALE_TRANSFORMATION_JOB_GRACE_SECONDS <= self.WORKER_JOB_TIMEOUT:
            raise ValueError(
                "STALE_TRANSFORMATION_JOB_GRACE_SECONDS must be greater than "
                "WORKER_JOB_TIMEOUT so a live-but-slow job is never treated as "
                "an orphaned/stuck job."
            )
        if (
            not isinstance(self.STALE_JOB_REAPER_INTERVAL_SECONDS, int)
            or isinstance(self.STALE_JOB_REAPER_INTERVAL_SECONDS, bool)
            or self.STALE_JOB_REAPER_INTERVAL_SECONDS < 60
            or self.STALE_JOB_REAPER_INTERVAL_SECONDS > 86400
        ):
            raise ValueError(
                "STALE_JOB_REAPER_INTERVAL_SECONDS must be an integer in "
                "[60, 86400]."
            )
        return self

    @model_validator(mode="after")
    def _validate_production_hardening(self) -> "Settings":
        """Fail closed for staging/production (Phase 13F).

        In a non-development environment the API refuses to boot with a
        development secret, a console OTP provider, an in-memory OTP store, or
        a wildcard CORS origin — configuration that would silently weaken the
        perimeter in production.
        """
        if self.ENVIRONMENT not in ("staging", "production"):
            return self

        if self.AUTH_SECRET_KEY == "dev-secret-replace-before-production":
            raise ValueError(
                "AUTH_SECRET_KEY must be a strong random secret in "
                f"{self.ENVIRONMENT}; refusing to boot with the development value."
            )
        if self.OTP_PROVIDER == "console":
            raise ValueError(
                f"OTP_PROVIDER='console' is not allowed in {self.ENVIRONMENT}; "
                "use an email or sms delivery provider."
            )
        if self.OTP_STORE_BACKEND == "memory":
            raise ValueError(
                f"OTP_STORE_BACKEND='memory' is not allowed in {self.ENVIRONMENT}; "
                "use the shared redis store."
            )
        origins = [
            o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()
        ]
        if "*" in origins:
            raise ValueError(
                f"ALLOWED_ORIGINS must not contain '*' in {self.ENVIRONMENT}."
            )
        return self

    @model_validator(mode="after")
    def _validate_production_provider_and_stores(self) -> "Settings":
        """Fail closed for production provider/storage configuration (Phase 14).

        In ``production`` the API refuses to boot with:
          * the security audit emitter disabled or the in-memory sink (a
            per-replica sink cannot persist events across replicas);
          * a fake/mock LLM or embedding provider, or a real provider without
            its API key;
          * memory-backed revocation / rate-limit / cache stores (per-replica
            and non-shared, which breaks revocation and coordinated limiting);
          * an incomplete S3 configuration (never silently falling back to
            local storage).

        ``staging`` stays permissive on providers (deployment validation uses
        deterministic offline providers), but an incomplete S3 configuration is
        still rejected so a staging/staging-like misconfiguration fails at boot
        instead of at first upload.
        """
        if self.ENVIRONMENT == "production":
            if not self.SECURITY_AUDIT_ENABLED:
                raise ValueError(
                    "SECURITY_AUDIT_ENABLED must be True in production; "
                    "refusing to run without the security audit emitter."
                )
            if self.SECURITY_AUDIT_SINK != "database":
                raise ValueError(
                    "SECURITY_AUDIT_SINK must be 'database' in production; "
                    "the in-memory sink cannot persist audit events across "
                    "replicas."
                )
            if self.LLM_PROVIDER == "fake":
                raise ValueError(
                    "LLM_PROVIDER='fake' is not allowed in production; "
                    "a real model provider is required."
                )
            if self.EMBEDDING_PROVIDER == "fake":
                raise ValueError(
                    "EMBEDDING_PROVIDER='fake' is not allowed in production; "
                    "a real embedding provider is required."
                )
            if self.LLM_PROVIDER != "fake" and not self.LLM_API_KEY:
                raise ValueError(
                    f"LLM_API_KEY is required in production when "
                    f"LLM_PROVIDER='{self.LLM_PROVIDER}'."
                )
            if self.EMBEDDING_PROVIDER == "openai" and not self.EMBEDDING_API_KEY:
                raise ValueError(
                    "EMBEDDING_API_KEY is required in production when "
                    "EMBEDDING_PROVIDER='openai'."
                )
            if self.AUTH_TOKEN_REVOCATION_STORE != "redis":
                raise ValueError(
                    "AUTH_TOKEN_REVOCATION_STORE must be 'redis' in production; "
                    "the in-memory store cannot share revocations across replicas."
                )
            if self.RATE_LIMIT_BACKEND != "redis":
                raise ValueError(
                    "RATE_LIMIT_BACKEND must be 'redis' in production; "
                    "the in-memory limiter is per-replica."
                )
            if self.CACHE_ENABLED and self.CACHE_BACKEND != "redis":
                raise ValueError(
                    "CACHE_BACKEND must be 'redis' in production when "
                    "CACHE_ENABLED is True."
                )

        if self.ENVIRONMENT in ("staging", "production"):
            if self.STORAGE_BACKEND == "s3":
                missing = [
                    name
                    for name, value in (
                        ("STORAGE_BUCKET", self.STORAGE_BUCKET),
                        ("STORAGE_ACCESS_KEY", self.STORAGE_ACCESS_KEY),
                        ("STORAGE_SECRET_KEY", self.STORAGE_SECRET_KEY),
                    )
                    if not value
                ]
                if missing:
                    raise ValueError(
                        "STORAGE_BACKEND='s3' requires "
                        f"{', '.join(missing)} to be set in {self.ENVIRONMENT}; "
                        "refusing to silently fall back to local storage."
                    )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


# Module-level singleton for convenience imports.
settings: Settings = get_settings()
