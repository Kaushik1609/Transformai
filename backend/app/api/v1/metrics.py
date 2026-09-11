"""Root-level metrics endpoint (Phase 11L-C).

Exposes the Prometheus ``/metrics`` scrape target. Placed at the root (not under
``/api/v1``) so monitoring/ingress tooling can scrape it without authentication,
exactly like ``/health``. Serves ``text/plain; version=0.0.4`` and merges local
process metrics with worker metrics aggregated through Redis. Redis being
unavailable is deliberately fail-open: the endpoint always returns local
metrics instead of raising or hanging (Phase 11L — monitoring must never
participate in request failure).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Response

from app.core.config import settings
from app.core.metrics import load_worker_metrics, render_metrics

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["metrics"])

_MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _collect_worker_metrics() -> dict:
    """Fetch worker metrics from Redis, failing open (empty) on any error."""
    try:
        import redis

        conn = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=2)
        return load_worker_metrics(conn)
    except Exception:  # pragma: no cover - Redis outage path
        logger.warning("worker_metrics_unavailable_failing_open")
        return {"counters": {}, "histograms": {}}


@router.get("/metrics", include_in_schema=False, summary="Prometheus metrics")
def metrics_endpoint() -> Response:
    """Return local + worker metrics in Prometheus text exposition format."""
    body = render_metrics(worker_metrics=_collect_worker_metrics())
    return Response(content=body, media_type=_MEDIA_TYPE)