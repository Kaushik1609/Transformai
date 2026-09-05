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

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    AUTH_SECRET_KEY: str = "dev-secret-replace-before-production"
    AUTH_ALGORITHM: str = "HS256"
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AUTH_TOKEN_TYPE: str = "bearer"

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

    @property
    def allowed_upload_types_list(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_UPLOAD_TYPES.split(",") if t.strip()]

    # -------------------------------------------------------------------------
    # Worker
    # -------------------------------------------------------------------------
    WORKER_CONCURRENCY: int = 2
    # The RQ worker timeout is a final safety backstop for queue jobs and MUST be
    # greater than (or equal to) the per-transformation execution budget so the
    # worker never terminates a job before its application-level budget elapses.
    WORKER_JOB_TIMEOUT: int = 605
    # Per-transformation execution budget (seconds). This job budget must exceed
    # the per-provider request timeout (LLM_TIMEOUT_SECONDS) and MUST NOT exceed
    # WORKER_JOB_TIMEOUT (enforced by the validator below).
    TRANSFORMATION_JOB_TIMEOUT: int = 600

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


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


# Module-level singleton for convenience imports.
settings: Settings = get_settings()
