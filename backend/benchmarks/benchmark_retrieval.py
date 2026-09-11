"""Phase 11J-C13: lightweight, optional retrieval benchmark.

Measures the pure-Python cosine ranking path (the SQLite/reference
implementation) that Phase 11J-C leaves in place for non-PostgreSQL dialects,
and prints a clearly-labeled THEORETICAL model for the PostgreSQL pgvector
exact pushdown path.

The benchmark is standalone and NOT part of the pytest suite. Run explicitly:

    python benchmarks/benchmark_retrieval.py            (single size config)
    python benchmarks/benchmark_retrieval.py --sizes 100 1000 10000 50000

Method:
  * "measured": wall-clock time to rank ``N`` stored 1536-dim vectors against
    one query vector using the reference ``_cosine_distance`` implementation
    executed in Python (list-based dot product + norms). This is the exact
    computation the current fallback performs per candidate.
  * "theoretical": time budget that PostgreSQL/pgvector would spend on the same
    ranking using the SQL pushdown. No PostgreSQL run is performed here, so this
    is explicitly labeled expected/theoretical, never measured.

No external API, no database writes, no network calls.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.service import RetrievalService

DIMS = 1536
QUERY_VECTOR = [0.5] + [0.05] * (DIMS - 1)


def _make_corpus(count: int) -> list[list[float]]:
    rng = random.Random(1337)
    vectors: list[list[float]] = []
    for _ in range(count):
        base = [rng.uniform(-1.0, 1.0) for _ in range(DIMS)]
        vectors.append(base)
    return vectors


def _measured_python_ranking(vectors: list[list[float]], rounds: int = 3) -> float:
    """Median wall time (seconds) to rank all vectors via the Python cosine path."""
    service = RetrievalService()
    timings: list[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        for vector in vectors:
            service._cosine_distance(QUERY_VECTOR, vector)
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def _theoretical_pg_projection(n: int, measured_python_seconds: float) -> dict:
    """Expected/modeled pgvector pushdown cost (clearly NOT measured).

    The PG path performs the same cosine math server-side but:
      * avoids transferring 1536 floats per candidate to the application,
      * avoids Python per-row loop overhead (loop, float parsing, math.sqrt),
      * returns at most ``top_k`` rows across the wire.

    We conservatively model the SQL-side per-row math as ~10x faster than the
    Python loop (C/SIMD vs interpreted Python) and treat row transfer savings
    as the dominant constant term. This is an estimate for planning, not a
    benchmark result.
    """
    python_per_row = measured_python_seconds / max(n, 1)
    estimated_pg_per_row = python_per_row / 10.0
    return {
        "n_candidates": n,
        "measured_python_total_s": measured_python_seconds,
        "measured_python_per_row_ms": python_per_row * 1000.0,
        "theoretical_pg_per_row_ms": estimated_pg_per_row * 1000.0,
        "theoretical_pg_total_estimate_s": estimated_pg_per_row * n,
        "theoretical_pg_transfer_rows": 5,  # only top_k rows cross the wire
        "label": "theoretical - not measured",
    }


def main(sizes: list[int]) -> None:
    print(f"Benchmarking {DIMS}-dim cosine ranking (query vector {len(QUERY_VECTOR)} dims)")
    print("=" * 78)
    print(
        f"{'candidates':>10} | {'Python total (s)':>16} | {'Python/row (ms)':>15} | "
        f"{'PG/row est (ms)':>15} | {'PG total est (s)':>15}"
    )
    print("-" * 78)
    for size in sizes:
        vectors = _make_corpus(size)
        measured = _measured_python_ranking(vectors)
        model = _theoretical_pg_projection(size, measured)
        print(
            f"{size:>10} | {measured:>16.4f} | "
            f"{model['measured_python_per_row_ms']:>15.4f} | "
            f"{model['theoretical_pg_per_row_ms']:>15.4f} | "
            f"{model['theoretical_pg_total_estimate_s']:>15.4f}"
        )
    print("=" * 78)
    print(
        "NOTE: PostgreSQL columns are THEORETICAL estimates (10x per-row math "
        "factor, top_k=5 row transfer). They are not measured; no PostgreSQL "
        "instance is touched by this script."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="*",
        default=[100, 1000, 10000],
        help="Candidate counts to benchmark (default: 100 1000 10000).",
    )
    args = parser.parse_args()
    main([n for n in args.sizes if n > 0])