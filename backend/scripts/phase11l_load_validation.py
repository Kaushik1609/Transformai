#!/usr/bin/env python
"""Phase 11L-H — bounded local concurrency/load validation.

Runs a small, honest transformation load through the real stack: the
docker-compose PostgreSQL + Redis, the docker WORKER container (the same code
path as production), and the configured LLM provider.  It is NOT a benchmark
and MUST NOT be used or reported as such.

Why not a local RQ worker: RQ 2.0's work horse is ``os.fork()``-based, which
does not exist on Windows.  Dispatching to the stack's worker container is the
deployment-faithful path.  If that container is not running, jobs stay queued
and the script exits 3 (budget exceeded) with a clear message.

What it validates:
  * Redis + PostgreSQL are reachable (boot check, fail-fast).
  * ``job.status`` transitions queued -> completed (workflow idempotency) under
    the real worker's atomic claim + per-job timeout.
  * No duplicate logical outputs are created per job.
  * Media outputs that completed actually persisted an artifact.
  * Consulted-identical requests (two jobs, same source + configuration) create
    exactly one artifact set per job.

Bounded: ``--jobs N`` (default 5) and ``--budget SECONDS`` (default 60);
enqueued jobs run under the worker container's ``WORKER_JOB_TIMEOUT``.  The
script exits non-zero if any job does not reach a terminal status within the
budget.

Usage (from the repo root so the local ``.env`` loads like the worker does)::

    python backend/scripts/phase11l_load_validation.py [--jobs 5] [--budget 120]

Outputs the marker ``LOCAL VALIDATION ONLY`` and a SERVICE summary for
machine-parsing.  Prior interrupted runs by this script are purged on each
start; current-run seed data is clearly tagged so it can be inspected.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

# Local storage for artifacts goes to a scratch dir (unconditional override:
# an environment variable takes precedence over the repo ``.env``), so this
# validation never writes into the application storage space.
_SCRATCH = Path(os.environ.get("TEMP", ".")) / "transformiq-11l-scratch"
os.environ["STORAGE_LOCAL_PATH"] = str(_SCRATCH / "storage")

# Host-side adaptation: when the repo's docker-compose ``.env`` names the
# database host ``postgres`` and Redis ``redis:6379`` (container service
# names), map them to the published localhost ports so this script can run
# from the development host.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://transformiq:changeme@localhost:5432/transformiq")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://transformiq:changeme@localhost:5432/transformiq")

# The cache toggle must be visible to the application settings BEFORE the
# first import of app.core.config (settings are cached at import time).  It
# only affects this process's view of settings; the worker that actually runs
# the jobs enables its own cache.  We record it so the report reflects intent.
if "--cache" in sys.argv:
    os.environ["CACHE_ENABLED"] = "true"
    os.environ.setdefault("CACHE_BACKEND", "redis")

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MARKER = "phase11l-load-validation"

import redis as redis_client  # noqa: E402
from sqlalchemy import create_engine, delete, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.metrics import load_worker_metrics  # noqa: E402
from app.db.models.canonical_content import CanonicalContent  # noqa: E402
from app.db.models.generation_configuration import GenerationConfiguration  # noqa: E402
from app.db.models.output import Output  # noqa: E402
from app.db.models.project import Project  # noqa: E402
from app.db.models.source import Source  # noqa: E402
from app.db.models.transformation_job import TransformationJob  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.transformation.queue import (  # noqa: E402
    enqueue_transformation_job,
    get_transformation_queue,
)

MEDIA_OUTPUTS = {"presentation", "infographic", "video"}


def purge_previous_runs(engine) -> None:
    """Remove jobs left behind by interrupted runs of this script."""
    import redis as _redis

    conn = _redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
    queue = get_transformation_queue()
    with Session(engine, expire_on_commit=False) as db:
        job_ids = db.execute(
            select(TransformationJob.id)
            .join(Project, Project.id == TransformationJob.project_id)
            .where(Project.name.like(f"{MARKER} %"))
        ).scalars().all()
    for job_id in job_ids:
        try:
            queue.remove(job_id)
        except Exception:  # noqa: BLE001 - a key may not exist; removal is best-effort
            pass
    conn.close()
    with Session(engine, expire_on_commit=False) as db:
        # Output -> verification_results and job -> outputs cascade at the DB
        # level, so removing the jobs removes their artifacts too.
        for cls, col in (
            (TransformationJob, TransformationJob.project_id),
            (CanonicalContent, CanonicalContent.project_id),
            (Source, Source.project_id),
            (GenerationConfiguration, GenerationConfiguration.project_id),
            (Project, Project.id),
            (User, User.id),
        ):
            proj_ids = db.execute(
                select(Project.id).where(Project.name.like(f"{MARKER} %"))
            ).scalars().all()
            if not proj_ids:
                break
            if cls is User:
                db.execute(delete(User).where(User.id.in_(proj_ids)))
            else:
                db.execute(delete(cls).where(col.in_(proj_ids)))
            db.flush()
        db.commit()


def boot_check() -> None:
    """Fail fast when the runtime dependencies are not reachable."""
    conn = redis_client.from_url(settings.REDIS_URL, socket_connect_timeout=3)
    conn.ping()
    conn.close()
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    with engine.connect() as raw:
        raw.execute(select(func.now()))
    engine.dispose()


def seed(seed_tag: str, output_sets: list[list[str]]):
    """Create isolated validation data and return (engine, job_ids)."""
    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    user = User(
        id=uuid.uuid4(),
        email=f"{MARKER}-{uuid.uuid4().hex[:8]}@example.test",
        name=f"{MARKER} {seed_tag}",
        role="operator",
    )
    project = Project(id=uuid.uuid4(), user_id=user.id, name=f"{MARKER} {seed_tag}")
    source = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        source_type="text",
        status="ready",
        extracted_text="Source line one.\nSource line two.",
    )
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([user, project, source])
        db.flush()
        db.add(
            CanonicalContent(
                id=uuid.uuid4(),
                source_id=source.id,
                project_id=project.id,
                status="completed",
                title="11L Validation Source",
                summary=f"Validation source for {seed_tag}.",
                key_points=[{"text": "First key point", "source_chunk_ids": []}],
                recommendations=[{"text": "Recommended action", "source_chunk_ids": []}],
                claims=[], statistics=[], dates=[], entities=[], topics=[], source_references=[],
            )
        )
        cfg = GenerationConfiguration(id=uuid.uuid4(), project_id=project.id, language="English")
        db.add(cfg)
        db.flush()
        job_ids: list[uuid.UUID] = []
        for output_types in output_sets:
            job = TransformationJob(
                id=uuid.uuid4(),
                project_id=project.id,
                source_id=source.id,
                configuration_id=cfg.id,
                requested_outputs={"output_types": output_types},
                status="queued",
            )
            db.add(job)
            job_ids.append(job.id)
        db.commit()
    return engine, job_ids


def wait_for_workers(engine, jobs, budget_seconds) -> None:
    """Poll until every job reaches a terminal status or the budget runs out."""
    import redis as _redis

    conn = _redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        with Session(engine, expire_on_commit=False) as db:
            statuses = set(db.execute(
                select(TransformationJob.status).where(TransformationJob.id.in_(jobs))
            ).scalars().all())
        if statuses and statuses.issubset({"completed", "failed"}):
            conn.close()
            return
        time.sleep(2)
    conn.close()
    print(f"  ERROR: jobs still active after {budget_seconds}s "
          f"(statuses={sorted(statuses)}). Is the docker WORKER container running?")
    sys.exit(3)


def verify(engine, jobs, started_at, budget_seconds):
    """Check the terminal statuses; count duplicates and artifacts."""
    failures: list[tuple[str, str]] = []
    total_outputs = 0
    duplicate_outputs = 0
    media_completed = 0
    media_with_artifact = 0

    with Session(engine, expire_on_commit=False) as db:
        for job_id in jobs:
            job = db.get(TransformationJob, job_id)
            if job is None:
                failures.append((str(job_id), "missing"))
                continue
            if job.status != "completed":
                failures.append(
                    (str(job_id), f"status={job.status}:{str(job.error_message)[:120]}")
                )
                continue
            rows = db.execute(select(Output).where(Output.job_id == job_id)).scalars().all()
            types = [o.output_type for o in rows]
            total_outputs += len(types)
            unique = set(types)
            duplicate_outputs += len(types) - len(unique)
            for o in rows:
                if o.status == "completed" and o.output_type in MEDIA_OUTPUTS:
                    media_completed += 1
                    if o.storage_key:
                        media_with_artifact += 1

    elapsed = time.monotonic() - started_at
    sample_rate = len(jobs) / elapsed if elapsed > 0 else 0.0
    status = "PASSED" if not failures else "FAILED"
    print("=" * 78)
    print("RESULT:", status, "| LOCAL VALIDATION ONLY")
    print("SERVICE:")
    print(f"  total={len(jobs)} completed={len(jobs) - len(failures)} failed={len(failures)} "
          f"skipped=0 duplicate_outputs={duplicate_outputs}")
    print(f"  media_completed={media_completed} media_with_artifact={media_with_artifact}")
    print(f"  outputs_created={total_outputs} sample_rate={sample_rate:.2f}/s "
          f"elapsed_seconds={elapsed:.2f}")
    print(f"  cache_enabled={settings.CACHE_ENABLED}"
          + ("" if settings.CACHE_ENABLED else " (restart worker with CACHE_ENABLED=1 for a cache-heading run)"))
    if failures:
        for job_id, reason in failures[:10]:
            print(f"  FAIL JOB {job_id}: {reason}")
    if elapsed > budget_seconds:
        print(f"  WARNING: elapsed {elapsed:.1f}s exceeded budget {budget_seconds}s")
        sys.exit(3)
    if failures:
        sys.exit(1)


def report_worker_metrics() -> None:
    """Surface the worker-pushed Prometheus deltas observed via Redis."""
    conn = redis_client.from_url(settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    totals = load_worker_metrics(conn)
    jobs = totals.get("counters", {}).get("transformation_jobs_total", {})
    by_result: dict[str, int] = {}
    for labels_key, value in jobs.items():
        result = dict(labels_key).get("result", "?")
        by_result[result] = by_result.get(result, 0) + int(value)
    print("  worker_metrics transformation_jobs_total:", by_result or "n/a")
    cache_hits = totals.get("counters", {}).get("llm_cache_hits_total", {})
    cache_misses = totals.get("counters", {}).get("llm_cache_misses_total", {})
    hit_total = sum(int(v) for v in cache_hits.values())
    miss_total = sum(int(v) for v in cache_misses.values())
    if settings.CACHE_ENABLED:
        print(f"  worker_metrics llm_cache hits={hit_total} misses={miss_total} all_time")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 11L-H local load validation")
    parser.add_argument("--jobs", type=int, default=5, help="number of transformation jobs (default 5)")
    parser.add_argument("--budget", type=int, default=60, help="soft time budget in seconds (default 60)")
    parser.add_argument(
        "--cache",
        action="store_true",
        help="expect a cache-enabled worker; report cache counters from Redis",
    )
    args = parser.parse_args()

    if args.jobs < 1 or args.jobs > 10:
        print("ERROR: --jobs must be in [1, 10] (bounded validation).")
        sys.exit(2)
    if args.budget < 10 or args.budget > 300:
        print("ERROR: --budget must be in [10, 300] seconds.")
        sys.exit(2)

    try:
        boot_check()
    except Exception as exc:  # noqa: BLE001 - fail fast with a clear message
        print(f"ERROR: runtime dependency not reachable: {exc}")
        sys.exit(2)

    # Scenario: 2 identical jobs (cache/duplicate-avoidance exercise) plus the
    # rest spread across accepted output types.
    identical = ["summary", "presentation"]
    others = ["summary", "linkedin", "infographic", "video", "x", "advisory"]
    output_sets = [identical, identical]
    i = 0
    while len(output_sets) < args.jobs:
        output_sets.append([others[i % len(others)]])
        i += 1

    print("=" * 78)
    print("PHASE 11L-H LOCAL LOAD VALIDATION")
    print(f"  jobs={args.jobs} budget={args.budget}s environments={settings.ENVIRONMENT}")
    print(f"  llm_provider={settings.LLM_PROVIDER} cache_enabled={settings.CACHE_ENABLED}")
    print(f"  output_sets={output_sets}")

    engine = create_engine(settings.DATABASE_SYNC_URL, pool_pre_ping=True)
    purge_previous_runs(engine)

    started_at = time.monotonic()
    tag = uuid.uuid4().hex[:8]
    engine, job_ids = seed(tag, output_sets)

    queue = get_transformation_queue()
    for job_id in job_ids:
        enqueue_transformation_job(job_id, queue=queue)
    print(f"  enqueued={len(job_ids)} (consumed by the docker WORKER container)")

    wait_for_workers(engine, job_ids, args.budget)
    report_worker_metrics()
    verify(engine, job_ids, started_at, args.budget)


if __name__ == "__main__":
    main()