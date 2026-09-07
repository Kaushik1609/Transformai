"""TransformIQ — Prometheus-compatible metrics (Phase 11L-C).

A small, dependency-free metrics registry that emits Prometheus text format
(``text/plain; version=0.0.4``). It intentionally does NOT depend on the
``prometheus-client`` package; only stdlib constructs are used so the backend
and the RQ worker share the exact same registry code.

Phase 11L constraints:
  * Bounded cardinality — metrics carry ONLY enumerable labels (HTTP method,
    normalized route, status code, provider, output type, result, bucket).
    High-cardinality values (user/project/source/job IDs, free-text, API keys,
    timestamps) are NEVER used as labels.
  * Fail-open — Redis connectivity problems during aggregation/exposition are
    swallowed and reported as local-only metrics; the /metrics endpoint must
    never raise or hang because Redis is unavailable.
  * Worker aggregation — the RQ worker increments counters/histograms in its
    own process, pushes *deltas* into shared Redis keys, and the backend
    /metrics endpoint merges local + worker totals. Deltas (not absolute
    values) mean a worker restart never double-counts its own work.
"""

from __future__ import annotations

import re
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Labelling helpers
# ---------------------------------------------------------------------------

_INVALID_LABEL_CHARS = re.compile(r'[\|:"={},\n\t\r\\]')


def _sanitize_label(value: Any, limit: int = 64) -> str:
    """Return a Prometheus-safe label value of bounded length."""
    text = _INVALID_LABEL_CHARS.sub("_", str(value))
    return text[:limit] or "unknown"


def labels_key(labels: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """Return a canonical, sorted, sanitized label key (ordering stable)."""
    if not labels:
        return ()
    return tuple(sorted((str(k), _sanitize_label(v)) for k, v in labels.items()))


def _encode_labels_key(key: tuple[tuple[str, str], ...]) -> str:
    """Encode a label key for use inside a Redis key (no reserved chars)."""
    return ";".join(f"{k}={v}" for k, v in key)


def _decode_labels_key(encoded: str) -> tuple[tuple[str, str], ...]:
    """Decode a label key produced by ``_encode_labels_key``."""
    if not encoded:
        return ()
    pairs: list[tuple[str, str]] = []
    for token in encoded.split(";"):
        if not token:
            continue
        name, _, value = token.partition("=")
        pairs.append((name, value))
    return tuple(sorted(pairs))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_DEFAULT_BUCKETS: tuple[float, ...] = (
    0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
)


class MetricsRegistry:
    """Thread-safe counters + histograms with Prometheus text rendering."""

    def __init__(self) -> None:
        # family name -> (help, labelnames)
        self._counters: dict[str, tuple[str, tuple[str, ...]]] = {}
        # family name -> (help, labelnames, buckets)
        self._histograms: dict[
            str, tuple[str, tuple[str, ...], tuple[float, ...]]
        ] = {}
        # (family, labels_key) -> total
        self._counter_values: dict[
            tuple[str, tuple[tuple[str, str], ...]], int
        ] = {}
        # (family, labels_key) -> {"bucket_counts": [...], "sum": float, "count": int}
        self._hist_values: dict[
            tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]
        ] = {}
        self._lock = threading.RLock()

    # -- registration -------------------------------------------------------

    def register_counter(
        self, name: str, help: str, labelnames: tuple[str, ...] = ()
    ) -> None:
        """Declare a counter family once (idempotent for the same signature)."""
        with self._lock:
            existing = self._counters.get(name)
            if existing is not None:
                if existing[0] != help or existing[1] != labelnames:
                    raise ValueError(
                        f"Counter {name!r} already registered with different help/labels."
                    )
                return
            self._counters[name] = (help, tuple(labelnames))

    def register_histogram(
        self,
        name: str,
        help: str,
        labelnames: tuple[str, ...] = (),
        buckets: tuple[float, ...] = _DEFAULT_BUCKETS,
    ) -> None:
        """Declare a histogram family once (idempotent for the same signature)."""
        with self._lock:
            existing = self._histograms.get(name)
            if existing is not None:
                if (
                    existing[0] != help
                    or existing[1] != labelnames
                    or existing[2] != buckets
                ):
                    raise ValueError(
                        f"Histogram {name!r} already registered with a different signature."
                    )
                return
            self._histograms[name] = (help, tuple(labelnames), tuple(buckets))

    def _required_labels(self, name: str) -> set[str]:
        if name in self._counters:
            return set(self._counters[name][1])
        if name in self._histograms:
            return set(self._histograms[name][1])
        raise KeyError(f"Metric family {name!r} is not registered.")

    def _validate_labels(self, name: str, labels: dict[str, Any] | None) -> None:
        required = self._required_labels(name)
        supplied = set((labels or {}).keys())
        unknown = supplied - required
        if unknown:
            raise ValueError(
                f"Unknown labels {sorted(unknown)} for family {name!r}; "
                f"expected {sorted(required)}."
            )
        missing = required - supplied
        if missing:
            raise ValueError(
                f"Missing labels {sorted(missing)} for family {name!r}; "
                f"required {sorted(required)}."
            )

    # -- observation --------------------------------------------------------

    def inc(
        self,
        name: str,
        labels: dict[str, Any] | None = None,
        amount: int = 1,
    ) -> None:
        """Increment a counter by ``amount`` (>= 1)."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("amount must be an integer >= 1.")
        self._validate_labels(name, labels)
        key = (name, labels_key(labels))
        with self._lock:
            self._counter_values[key] = self._counter_values.get(key, 0) + amount

    def observe(
        self, name: str, value: float, labels: dict[str, Any] | None = None
    ) -> None:
        """Record one observation for a histogram family."""
        if name not in self._histograms:
            raise KeyError(f"Histogram {name!r} is not registered.")
        self._validate_labels(name, labels)
        _, _, buckets = self._histograms[name]
        key = (name, labels_key(labels))
        with self._lock:
            entry = self._hist_values.setdefault(
                key,
                {
                    "bucket_counts": [0] * (len(buckets) + 1),
                    "sum": 0.0,
                    "count": 0,
                },
            )
            entry["sum"] += float(value)
            entry["count"] += 1
            observed = float(value)
            bucket_index = len(buckets)
            for index, edge in enumerate(buckets):
                if observed <= edge:
                    bucket_index = index
                    break
            entry["bucket_counts"][bucket_index] += 1

    def reset(self) -> None:
        """Clear all observed values but keep family declarations."""
        with self._lock:
            self._counter_values.clear()
            self._hist_values.clear()

    def _absorb(self, data: dict[str, Any]) -> None:
        """Merge previously-taken deltas back (used when a Redis push fails).

        ``data`` uses the same shape as ``snapshot()``/``take_deltas()``:
        ``counters[name][labels_key]`` and ``histograms[name][labels_key]``.
        """
        with self._lock:
            for name, label_map in (data.get("counters") or {}).items():
                for lk, value in label_map.items():
                    self._counter_values[(name, lk)] = (
                        self._counter_values.get((name, lk), 0) + int(value)
                    )
            for name, label_map in (data.get("histograms") or {}).items():
                for lk, entry in label_map.items():
                    current = self._hist_values.setdefault(
                        (name, lk),
                        {
                            "bucket_counts": [0] * len(entry["bucket_counts"]),
                            "sum": 0.0,
                            "count": 0,
                        },
                    )
                    for index, count in enumerate(entry["bucket_counts"]):
                        if index < len(current["bucket_counts"]):
                            current["bucket_counts"][index] += int(count)
                    current["sum"] += float(entry["sum"])
                    current["count"] += int(entry["count"])

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of all observed state::

            {
              "counters":   {name: {labels_key: int}},
              "histograms": {name: {labels_key: {"bucket_counts": [...],
                                                 "sum": float, "count": int}}},
            }
        """
        with self._lock:
            counters: dict[str, dict[Any, int]] = {}
            for (name, lk), value in self._counter_values.items():
                counters.setdefault(name, {})[lk] = int(value)
            histograms: dict[str, dict[Any, dict[str, Any]]] = {}
            for (name, lk), entry in self._hist_values.items():
                histograms.setdefault(name, {})[lk] = {
                    "bucket_counts": list(entry["bucket_counts"]),
                    "sum": entry["sum"],
                    "count": entry["count"],
                }
            return {"counters": counters, "histograms": histograms}

    def take_deltas(self) -> dict[str, Any]:
        """Return observed state and then reset it (for worker Redis pushes).

        Prometheus scrapes are cumulative, so the worker must push deltas that
        accumulate in Redis as running totals across all workers and restarts.
        """
        data = self.snapshot()
        self.reset()
        return data


# Module-level default registry shared by backend + worker processes.
metrics = MetricsRegistry()


# ---------------------------------------------------------------------------
# Pre-registration of the Phase 11L metric families
# ---------------------------------------------------------------------------

def _register_default_families() -> None:
    metrics.register_counter(
        "http_requests_total",
        "Total HTTP requests served, by method/route/status.",
        ("method", "route", "status"),
    )
    metrics.register_histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds, by method/route.",
        ("method", "route"),
    )
    metrics.register_counter(
        "transformations_requested_total",
        "Transformation jobs requested via the API.",
    )
    metrics.register_counter(
        "transformation_jobs_enqueued_total",
        "Transformation jobs enqueued to the RQ transformation queue.",
        ("queue",),
    )
    metrics.register_counter(
        "transformation_jobs_total",
        "Transformation jobs processed by the worker, by result.",
        ("result",),
    )
    metrics.register_histogram(
        "transformation_job_duration_seconds",
        "Wall-clock duration of a transformation job in the worker.",
    )
    metrics.register_counter(
        "transformation_outputs_total",
        "Generated outputs persisted by the worker, by output type and result.",
        ("output_type", "result"),
    )
    metrics.register_counter(
        "ingestion_jobs_total",
        "Ingestion-family jobs processed by the worker, by kind and result.",
        ("kind", "result"),
    )
    metrics.register_counter(
        "llm_requests_total",
        "LLM generation requests issued by the worker, by provider.",
        ("provider",),
    )
    metrics.register_histogram(
        "llm_request_duration_seconds",
        "LLM generation latency in seconds, by provider.",
        ("provider",),
    )
    metrics.register_counter(
        "llm_failures_total",
        "LLM generation failures observed, by provider.",
        ("provider",),
    )
    metrics.register_counter(
        "rag_retrievals_total",
        "RAG retrieval operations performed by the worker.",
    )
    metrics.register_counter(
        "rag_retrieval_failures_total",
        "RAG retrieval operations that failed.",
    )
    metrics.register_histogram(
        "rag_retrieval_duration_seconds",
        "RAG retrieval latency in seconds.",
    )
    metrics.register_counter(
        "llm_cache_hits_total",
        "LLM cache hits served without calling the provider.",
        ("provider",),
    )
    metrics.register_counter(
        "llm_cache_misses_total",
        "LLM cache misses that called the provider.",
        ("provider",),
    )
    metrics.register_counter(
        "llm_cache_errors_total",
        "LLM cache backend errors (fail-open: provider still called).",
        ("provider",),
    )
    metrics.register_counter(
        "artifacts_saved_total",
        "Binary artifacts persisted to object storage.",
    )
    metrics.register_counter(
        "artifacts_saved_bytes_total",
        "Cumulative bytes persisted across artifacts.",
    )
    metrics.register_counter(
        "artifacts_failed_total",
        "Artifact persistence failures.",
    )
    metrics.register_histogram(
        "artifact_save_duration_seconds",
        "Artifact persistence latency in seconds.",
    )
    metrics.register_counter(
        "rate_limit_triggered_total",
        "Requests denied by the rate limiter, by bucket.",
        ("bucket",),
    )
    metrics.register_counter(
        "authn_denials_total",
        "Authentication denials, by reason.",
        ("reason",),
    )
    metrics.register_counter(
        "authz_denials_total",
        "Authorization (RBAC role) denials.",
    )


_register_default_families()


# ---------------------------------------------------------------------------
# Prometheus text rendering
# ---------------------------------------------------------------------------

def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_labels(
    labels: tuple[tuple[str, str], ...],
    extra: dict[str, str] | None = None,
) -> str:
    pairs = list(labels)
    if extra:
        pairs.extend((k, str(v)) for k, v in extra.items())
    if not pairs:
        return ""
    body = ",".join(
        f'{k}="{_escape_label_value(v)}"' for k, v in sorted(pairs)
    )
    return "{" + body + "}"


def render_metrics(registry: MetricsRegistry = metrics, worker_metrics: dict[str, Any] | None = None) -> str:
    """Render metrics in Prometheus text format.

    ``worker_metrics`` is the structure returned by ``load_worker_metrics``
    (or ``None`` for local-only output). Local state and worker-provided
    totals are summed per family/label-key so scraping reflects the whole
    deployment, not just this API process.
    """
    snapshot = registry.snapshot()
    counters: dict[str, dict[Any, int]] = {
        name: dict(by_labels) for name, by_labels in (snapshot["counters"] or {}).items()
    }
    histograms: dict[str, dict[Any, dict[str, Any]]] = {
        name: {
            lk: {
                "bucket_counts": list(entry["bucket_counts"]),
                "sum": entry["sum"],
                "count": entry["count"],
            }
            for lk, entry in by_labels.items()
        }
        for name, by_labels in (snapshot["histograms"] or {}).items()
    }

    workers = worker_metrics or {}
    for name, by_labels in (workers.get("counters") or {}).items():
        target = counters.setdefault(name, {})
        for lk, value in by_labels.items():
            target[lk] = target.get(lk, 0) + int(value)
    for name, by_labels in (workers.get("histograms") or {}).items():
        for lk, entry in by_labels.items():
            target = histograms.setdefault(name, {})
            current = target.get(lk)
            if current is None:
                current = {"bucket_counts": [], "sum": 0.0, "count": 0}
                target[lk] = current
            _merge_histogram(current, entry, registry)

    lines: list[str] = []

    for name, (help, labelnames) in sorted(registry._counters.items()):
        lines.append(f"# HELP {name} {help}")
        lines.append(f"# TYPE {name} counter")
        for lk, value in sorted((counters.get(name) or {}).items(), key=lambda item: _encode_labels_key(item[0])):
            lines.append(f"{name}{_format_labels(lk)} {int(value)}")

    for name, (help, labelnames, buckets) in sorted(registry._histograms.items()):
        lines.append(f"# HELP {name} {help}")
        lines.append(f"# TYPE {name} histogram")
        for lk, entry in sorted((histograms.get(name) or {}).items(), key=lambda item: _encode_labels_key(item[0])):
            _render_histogram_family(lines, name, lk, entry, buckets)

    return "\n".join(lines) + "\n"


def _merge_histogram(current: dict[str, Any], entry: dict[str, Any], registry: MetricsRegistry) -> None:
    """Merge a worker histogram entry into the local accumulation."""
    current["sum"] = float(current["sum"]) + float(entry.get("sum", 0.0))
    current["count"] = int(current["count"]) + int(entry.get("count", 0))
    worker_buckets = entry.get("bucket_counts") or {}
    for index, count in worker_buckets.items():
        index = int(index)
        while len(current["bucket_counts"]) <= index:
            current["bucket_counts"].append(0)
        current["bucket_counts"][index] += int(count)


def _render_histogram_family(
    lines: list[str],
    name: str,
    lk: tuple[tuple[str, str], ...],
    entry: dict[str, Any],
    buckets: tuple[float, ...],
) -> None:
    """Append Prometheus histogram lines for one label-key series."""
    bucket_counts = list(entry["bucket_counts"])
    while len(bucket_counts) < len(buckets) + 1:
        bucket_counts.append(0)
    cumulative = 0
    for index, edge in enumerate(buckets):
        cumulative += bucket_counts[index]
        lines.append(
            f"{name}_bucket{_format_labels(lk, {'le': str(edge)})} {cumulative}"
        )
    cumulative += bucket_counts[-1]
    lines.append(f"{name}_bucket{_format_labels(lk, {'le': '+Inf'})} {cumulative}")
    lines.append(f"{name}_sum{_format_labels(lk)} {float(entry['sum'])}")
    lines.append(f"{name}_count{_format_labels(lk)} {int(entry['count'])}")


# ---------------------------------------------------------------------------
# Worker metrics aggregation over shared Redis keys
# ---------------------------------------------------------------------------

_METRIC_PREFIX = "tq:metric"
_COUNTER_PREFIX = f"{_METRIC_PREFIX}:c"
_BUCKET_PREFIX = f"{_METRIC_PREFIX}:h"
_SUM_PREFIX = f"{_METRIC_PREFIX}:hs"
_COUNT_PREFIX = f"{_METRIC_PREFIX}:hn"


def _to_microseconds(value: float) -> int:
    return int(round(float(value) * 1_000_000.0))


def push_worker_metrics(conn, registry: MetricsRegistry = metrics) -> int:
    """Push this worker process's deltas into shared Redis running totals.

    Returns the number of Redis commands issued, or 0 when the push failed
    (deltas are absorbed back so nothing is lost; the job pipeline is never
    blocked by metrics).
    """
    data = registry.take_deltas()
    commands = 0
    try:
        with conn.pipeline(transaction=False) as pipe:
            for name, label_map in (data.get("counters") or {}).items():
                for lk, value in label_map.items():
                    key = f"{_COUNTER_PREFIX}:{name}:{_encode_labels_key(lk)}"
                    pipe.incrby(key, int(value))
                    commands += 1
            for name, label_map in (data.get("histograms") or {}).items():
                for lk, entry in label_map.items():
                    enc = _encode_labels_key(lk)
                    for index, count in enumerate(entry["bucket_counts"]):
                        if count:
                            pipe.incrby(f"{_BUCKET_PREFIX}:{name}:{index}:{enc}", int(count))
                            commands += 1
                    pipe.incrby(f"{_SUM_PREFIX}:{name}:{enc}", _to_microseconds(entry["sum"]))
                    pipe.incrby(f"{_COUNT_PREFIX}:{name}:{enc}", int(entry["count"]))
                    commands += 2
            pipe.execute()
        return commands
    except Exception:
        # Fail-open: restore the deltas and report failure (metrics only).
        registry._absorb(data)
        return 0


def _parse_metric_key(key: str) -> tuple[str, str, str, str] | None:
    """Parse a worker metric Redis key into (family, kind, bucket_idx, labels)."""
    parts = key.split(":")
    # tq:metric:c:<name>:<labels> or tq:metric:h:<name>:<bucket>:<labels> etc.
    if len(parts) < 4 or parts[0] != "tq" or parts[1] != "metric":
        return None
    kind = parts[2]
    rest = ":".join(parts[3:])
    if kind == "c":
        name, _, labels = rest.partition(":")
        return (name, "counter", "", labels or "")
    if kind in ("hs", "hn"):
        name, _, labels = rest.partition(":")
        return (name, "sum" if kind == "hs" else "count", "", labels or "")
    if kind == "h":
        name, _, tail = rest.partition(":")
        bucket_idx, _, labels = tail.partition(":")
        return (name, "bucket", bucket_idx, labels or "")
    return None


def load_worker_metrics(conn) -> dict[str, Any]:
    """Read cumulative worker metric totals from Redis.

    Returns ``{"counters": {...}, "histograms": {...}}`` always; on any Redis
    failure the empty structure is returned (fail-open).
    """
    result: dict[str, Any] = {"counters": {}, "histograms": {}}
    try:
        keys = conn.keys(f"{_METRIC_PREFIX}:*")
    except Exception:
        return result
    if not keys:
        return result
    try:
        values = conn.mget(keys)
    except Exception:
        return result

    counters: dict[str, dict[Any, int]] = {}
    histograms: dict[str, dict[Any, dict[str, Any]]] = {}
    for key, value in zip(keys, values):
        if value is None:
            continue
        try:
            parsed = _parse_metric_key(key.decode())
            if parsed is None:
                continue
            family, kind, bucket_idx, labels_enc = parsed
            lk = _decode_labels_key(labels_enc)
        except Exception:
            continue
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if kind == "counter":
            inner = counters.setdefault(family, {})
            inner[lk] = inner.get(lk, 0) + numeric
        else:
            entry = histograms.setdefault(
                family, {}
            ).setdefault(
                lk, {"bucket_counts": {}, "sum": 0.0, "count": 0}
            )
            if kind == "bucket":
                entry["bucket_counts"][bucket_idx] = (
                    entry["bucket_counts"].get(bucket_idx, 0) + numeric
                )
            elif kind == "sum":
                entry["sum"] = entry["sum"] + numeric / 1_000_000.0
            elif kind == "count":
                entry["count"] = entry.get("count", 0) + numeric

    result["counters"] = counters
    result["histograms"] = histograms
    return result