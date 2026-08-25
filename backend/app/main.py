"""
TransformIQ Backend
FastAPI application entry point.
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import configure_logging
from app.api.v1.health import router as health_router
from app.api.v1 import router as api_v1_router

configure_logging()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info(
        "TransformIQ backend starting",
        environment=settings.ENVIRONMENT,
        version="0.1.0",
    )
    yield
    logger.info("TransformIQ backend shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TransformIQ API",
    description="Gen AI Platform for Automated Content Transformation — SIH 26154",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Return a consistent JSON error body for all HTTP exceptions."""
    logger.warning(
        "HTTP error",
        status_code=exc.status_code,
        detail=exc.detail,
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return structured validation errors as 422 JSON responses."""
    logger.warning(
        "Request validation error",
        errors=exc.errors(),
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions.
    Logs the error and returns a safe 500 response.
    Sensitive details are never exposed to callers.
    """
    logger.error(
        "Unhandled exception",
        exc_type=type(exc).__name__,
        path=str(request.url.path),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Health/ready endpoints are intentionally at the root (not /api/v1) so
# orchestration tools and load balancers can reach them without auth.
app.include_router(health_router)

# Versioned API router — all domain endpoints will be registered here.
app.include_router(api_v1_router, prefix="/api/v1")
