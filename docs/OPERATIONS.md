# TransformIQ — Operations, Backup & Recovery

This document is the operational companion to `docker-compose.prod.yml`.
It covers: what is stateful vs rebuildable, backup commands, recovery
procedures, the deployment runbook, and the monitoring contract.

## 1. Deployment runbook

Prerequisite: a `.env.production` file exists and every `<...>` placeholder has
been replaced (start from `.env.production.example`). The stack runs under its
own compose project (`transformiq-prod`) so it coexists with the development
stack; if the host ports `8000`/`3000` are taken, set `BACKEND_BIND_PORT` /
`FRONTEND_BIND_PORT` in `.env.production`.

```bash
# 1. Build all images (production frontend target, standalone Next.js output).
docker compose --env-file .env.production -f docker-compose.prod.yml build

# 2. Validate the rendered compose configuration.
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet

# 3. Bring the stack up. The `migrate` service runs `alembic upgrade head`
#    first; the backend refuses to start until it completes successfully.
docker compose --env-file .env.production -f docker-compose.prod.yml up -d

# 4. Confirm health.
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
curl -fsS http://localhost:3000/      # frontend

# 5. Scale the RQ worker replicas (each replica runs WORKER_COUNT processes).
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --scale worker=2
```

Public surface: only `backend:8000` and `frontend:3000` publish ports.
PostgreSQL, Redis, MinIO, ClamAV and the worker publish nothing; the stateful
services additionally sit on the Docker `internal: true` `data` network with no
Internet route.

## 2. Stateful vs rebuildable

| Component | State | Policy |
| --- | --- | --- |
| PostgreSQL (`postgres_data`) | **Back up** | Rows/relations are canonical transactional state. |
| S3/MinIO (`minio_data`) | **Back up** | Source files + generated artifacts and integrity hashes. `storage_data` (local adapter) is the equivalent when `STORAGE_BACKEND=local`. |
| Redis (`redis_data`) | Rebuildable | Job queue + cache + shared stores. Queued jobs can be re-enqueued from PostgreSQL (a `pending` job in the DB), the integrity cache re-warms, revocations are a denylist. Optional RDB/AOF snapshot is acceptable but never a recovery source of truth. |
| ClamAV signatures (`clamav_data`) | Rebuildable | Re-downloaded by freshclam on a fresh volume. |
| Configuration / secrets (`.env.production`, any secret-manager entries) | **Back up** | The stack cannot boot without them; they must never live in git. |

Backup all four secrets/state classes; never treat Redis or ClamAV volumes as a
backup requirement.

## 3. Backups

### 3.1 PostgreSQL (canonical source of truth)

```bash
# Use the Postgres server version's pg_dump, not a random host binary.
docker compose --env-file .env.production -f docker-compose.prod.yml \
  exec postgres pg_dump -U "$POSTGRES_USER" -Fc -d "$POSTGRES_DB" \
  > pipeline_backup_$(date +%Y%m%d_%H%M%S).dump
```

- Take the dump **off-host** (object storage / backup appliance) and encrypt at rest.
- Verify the dump by restoring into a throwaway container before trusting it:
  `pg_restore --list backup.dump | head` (sanity) plus a full restore exercise in staging.
- Retention: keep daily for 14 days, weekly for 3 months, monthly for a year
  (align with your compliance requirements).

### 3.2 S3 / MinIO artifacts

```bash
# From a host with MinIO client (or inside the worker container):
mc alias set pipeline https://<minio-console-or-endpoint> <user> <password>
mc mirror --watch --overwrite pipeline/transformiq/ s3://offsite-backup/transformiq/
```

Or use your S3-compatible tooling (rclone, Velero) against the same endpoint.
Enable bucket versioning on MinIO (`mc version enable pipeline/transformiq`) to
protect against accidental overwrite/deletion between snapshots.

### 3.3 Configuration and secrets

`.env.production`, service-account credentials, TLS key material, and any
`INTEGRITY_LEDGER_CREDENTIAL`-style entries must be stored in a secrets manager
or equivalent vault. Document, in the vault, exactly which image tag and
`docker-compose.prod.yml`/`.env.production.example` version the rollback target
corresponds to (pin images by digest or tag at deploy time).

## 4. Recovery procedures

### 4.1 Full-stack restore into an empty installation

1. Restore `.env.production` (and TLS material) from the secrets vault.
2. `docker compose --env-file .env.production -f docker-compose.prod.yml up -d`
   (fresh volumes; `migrate` runs `alembic upgrade head` and builds the schema).
3. Restore PostgreSQL:
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml \
     exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     --clean --if-exists < pipeline_backup.dump
   ```
   Because migrations ran first, the restore targets an already-current schema
   (restoring a dump over a migrated-but-empty schema is idempotent for app data).
4. Restore S3/MinIO objects (`mc mirror` in the reverse direction).
5. `docker compose --env-file .env.production -f docker-compose.prod.yml restart backend worker`
6. Verify: `curl -fsS http://localhost:8000/ready` returns 200; spot-check a
   known transformation job and its artifact in the bucket.

### 4.2 Single-state recovery

- **Database corruption**: stop the stack, `restore-volume`-style recover
  PostgreSQL, then replay via a fresh `docker compose up -d` (the backend
  depends on `migrate` completing).
- **Lost queue (Redis)**: restart Redis fresh; `pending` jobs are re-enqueued by
  re-triggering them from the API (or by re-submitting the source). No data is
  lost — only in-flight work.
- **Lost artifacts (MinIO)**: restore from the off-site mirror; integrity
  hashes in `output_metadata` will verify rebuilt/missing objects.

## 5. Monitoring contract

| Endpoint | Purpose | Expected |
| --- | --- | --- |
| `/health` | Liveness | 200 `{"status":"ok",...}` |
| `/ready` | Readiness | 200 when Redis + PostgreSQL (+ required ClamAV) reachable; 503 otherwise |
| `/metrics` | Prometheus | Numeric probe + job + auth/revocation + transformation metrics; unauthenticated by design — gate at the proxy to the monitoring CIDR |
| `/api/v1/security/events` | Audit trail | Drain from the `database` sink (`SECURITY_AUDIT_SINK=database` is enforced in production) |

Alert on: `ready` 503 for >1 interval, `worker` restart loops, spam/OTP rate
limit hits, and any `SecurityEvent` with `level=critical`.

## 6. Secrets rotation

- `AUTH_SECRET_KEY`: generate a new value, update `.env.production` and secret
  manager in lockstep, `docker compose ... up -d --force-recreate backend worker
  migrate`. Revoked tokens ride in Redis; rotate the store cleanly too
  (`FLUSHDB` on dedicated queue Redis or a fresh volume).
- SMTP / LLM / embedding keys: rotate at the provider, update env + vault,
  recreate the affected service containers.