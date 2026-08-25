"""
TransformIQ Backend — Structured Logging Configuration

Uses structlog for consistent, structured log output.
Sensitive content (API keys, document content) must never be logged.
"""
import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    """Configure structlog and stdlib logging for the application."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Configure stdlib logging so libraries (SQLAlchemy, httpx, etc.) also
    # go through structlog rendering.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    # Suppress noisy libraries at a higher threshold in development.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Shared processors applied to every log event.
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.ENVIRONMENT == "development":
        # Human-readable colored output for local development.
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        # JSON output for production log aggregation.
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        # Use stdlib BoundLogger so structlog loggers work with Python's
        # standard logging infrastructure (no .name attribute issue).
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
