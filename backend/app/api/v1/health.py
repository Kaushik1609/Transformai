"""
TransformIQ Backend — Health and Readiness Endpoints

/health  — liveness probe: the process is running.
/ready   — readiness probe: required dependencies (DB, Redis) are reachable.

These endpoints are intentionally at the root (not under /api/v1) so
Kubernetes/Docker health checks and load balancers can reach them without
authentication headers.
"""
import time

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["observability"])

# Record process start time for uptime reporting.
_START_TIME = time.time()


def _clamav_reachable() -> bool:
    """Return True if the ClamAV daemon accepts TCP connections.

    A PING/PONG protocol exchange is not required for readiness: a listening
    TCP socket on CLAMAV_HOST:CLAMAV_PORT is sufficient to declare the scan
    daemon reachable from this container.
    """
    import socket

    try:
        with socket.create_connection(
            (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=3
        ):
            return True
    except Exception:
        return False


@router.get("/health", summary="Liveness probe")
async def health() -> JSONResponse:
    """
    Returns 200 if the process is alive.
    Used by Docker/orchestration to decide whether to restart the container.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "service": "transformiq-backend",
            "version": "0.1.0",
            "environment": settings.ENVIRONMENT,
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        },
    )


@router.get("/ready", summary="Readiness probe")
async def ready() -> JSONResponse:
    """
    Returns 200 if all required dependencies are reachable.
    Returns 503 if any required dependency is unavailable.

    Required dependencies: Redis, PostgreSQL, and (when malware scanning is
    enabled with the ClamAV scanner and declared required) the ClamAV daemon.
    A non-required scan backend is reported but never blocks readiness.
    """
    checks: dict[str, str] = {}
    all_ready = True

    # ------------------------------------------------------------------
    # Redis check
    # ------------------------------------------------------------------
    try:
        import redis as redis_lib

        conn = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        conn.ping()
        conn.close()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Redis readiness check failed", error=str(exc))
        checks["redis"] = "unavailable"
        all_ready = False

    # ------------------------------------------------------------------
    # PostgreSQL check
    # Only tests that a TCP connection can be established.
    # Full schema/migration verification is Phase 2.
    # ------------------------------------------------------------------
    try:
        import psycopg2

        # Parse the sync URL (psycopg2-compatible, no asyncpg prefix).
        db_url = settings.DATABASE_SYNC_URL
        conn_pg = psycopg2.connect(db_url, connect_timeout=3)
        conn_pg.close()
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("Database readiness check failed", error=str(exc))
        checks["database"] = "unavailable"
        all_ready = False

    # ------------------------------------------------------------------
    # ClamAV check (Phase 14)
    # Reported only when malware scanning is enabled with the ClamAV
    # scanner. When the scan is required, an unreachable daemon fails
    # readiness (fail-closed); otherwise it is reported but does not block
    # serving (degraded-but-runnable).
    # ------------------------------------------------------------------
    if settings.MALWARE_SCAN_ENABLED and settings.MALWARE_SCANNER == "clamav":
        if _clamav_reachable():
            checks["clamav"] = "ok"
        else:
            checks["clamav"] = "unavailable"
            if settings.MALWARE_SCAN_REQUIRED:
                all_ready = False

    status_code = 200 if all_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ready else "not_ready",
            "checks": checks,
        },
    )
