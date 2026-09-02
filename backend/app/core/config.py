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
    # Embedding
    # -------------------------------------------------------------------------
    EMBEDDING_PROVIDER: str = "fake"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

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


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


# Module-level singleton for convenience imports.
settings: Settings = get_settings()
