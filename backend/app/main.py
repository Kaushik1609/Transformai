"""
TransformIQ Backend
FastAPI application entry point.
"""
from contextlib import asynccontextmanager
import asyncio
import time

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.metrics import metrics
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1 import router as api_v1_router

configure_logging()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle.

    Phase 13G: when enabled, a background reaper task fails transformation jobs
    stuck in ``running`` past the configured grace period (workers that died
    mid-job). It is cancelled on shutdown so a graceful stop never leaks tasks.
    """
    from app.core.config import settings as _settings

    reaper_task = None
    if _settings.STALE_JOB_REAPER_ENABLED:
        from app.transformation.reaper import run_stale_job_reaper_loop

        reaper_task = asyncio.create_task(
            run_stale_job_reaper_loop(_settings.STALE_JOB_REAPER_INTERVAL_SECONDS)
        )

    logger.info(
        "TransformIQ backend starting",
        environment=settings.ENVIRONMENT,
        version="0.1.0",
    )
    try:
        yield
    finally:
        if reaper_task is not None:
            reaper_task.cancel()
            try:
                await reaper_task
            except asyncio.CancelledError:
                pass
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
# HTTP metrics (Phase 11L-C)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def http_metrics_middleware(request: Request, call_next):
    """Record per-route HTTP request count and latency.

    The route is normalized to the literal route pattern (``request.scope``
    ``route.path``) — never the concrete path — so error pages, unknown routes
    and the metrics scrape itself stay low-cardinality.  ``unrouted`` is used
    when routing did not resolve a route (e.g. early lifecycle requests).
    """
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        status_code = 500
        raise
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None)
        if not route_path:
            route_path = "unrouted"
        method = (request.method or "UNKNOWN").upper()
        duration = time.perf_counter() - started
        metrics.inc(
            "http_requests_total",
            {"method": method, "route": route_path, "status": str(status_code)},
        )
        metrics.observe(
            "http_request_duration_seconds",
            duration,
            {"method": method, "route": route_path},
        )
    return response

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

# Prometheus scrape target — root level, unauthenticated, like /health.
app.include_router(metrics_router)

# Versioned API router — all domain endpoints will be registered here.
app.include_router(api_v1_router, prefix="/api/v1")
