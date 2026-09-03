"""
TransformIQ Backend — Application Configuration

All configuration is read from environment variables.
Never hard-code secrets or credentials here.
"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    EMBEDDING_PROVIDER: str = "fake"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

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
    WORKER_JOB_TIMEOUT: int = 300
    # Per-transformation execution budget (seconds). The Q worker timeout is a
    # final safety backstop and should be greater than this job budget, which in
    # turn must exceed the per-provider request timeout (LLM_TIMEOUT_SECONDS).
    TRANSFORMATION_JOB_TIMEOUT: int = 600


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


# Module-level singleton for convenience imports.
settings: Settings = get_settings()
