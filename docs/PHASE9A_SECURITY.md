# Phase 9A — Authentication, Authorization & Strict User/Resource Isolation

This document describes the security model implemented in Phase 9A for
TransformIQ. It establishes a reliable authorization boundary so that each user
can only reach the resources they own, and cannot reach — even by guessing IDs —
resources belonging to any other user.

## 1. Security Principles

1. **Authentication identifies the user.** `get_current_user()` resolves the
   authenticated identity for every protected request.
2. **Authorization determines access.** Every protected resource operation is
   enforced server-side. Client-supplied `project_id`, `source_id`,
   `transformation_id`, `output_id`, and storage/artifact keys are never trusted
   on their own.
3. **Prefer database-level scoping.** Ownership is enforced as early as possible
   in the data-access path (SQL `WHERE`/`JOIN`), not via a late Python check
   after fetching a potentially unauthorized row. This eliminates accidental
   authorization-bypass paths (IDOR / BOLA).

## 2. Logical Ownership Model

```
User
 |
 +-- Project
       |
       +-- Source
       |
       +-- TransformationJob
       |
       +-- Output
       |
       +-- VerificationResult
       |
       +-- Artifacts (storage keys rooted under the owning project)
```

No `user_id` is duplicated across every table. The existing relational schema
already provides a complete, safe ownership path for every resource:

| Resource              | Ownership Chain                          |
|-----------------------|------------------------------------------|
| Project               | `project.user_id`                        |
| Source                | `source.project_id -> project.user_id`   |
| TransformationJob     | `job.project_id -> project.user_id`      |
| Output                | `output.job_id -> job.project_id -> project.user_id` |
| VerificationResult    | `verification.output_id -> output.job_id -> job.project_id -> project.user_id` |
| Artifact (download)   | resolved from an authorized Output record only (server-side key) |
| RAG chunks            | `chunk.source_id -> source.project_id -> project.user_id` |

**No database migration is required.** The existing relationships provide full
ownership resolution; Phase 9A added SQL-level scoped lookup methods and
worker-side integrity checks on top of them.

## 3. Authorization Rule

For a directly-owned resource (a project):

```
resource.user_id == current_user.id
```

For project-owned resources:

```
resource.project_id -> project.user_id == current_user.id
```

A request that fails authorization is returned as **HTTP 404**, indistinguishable
from a nonexistent resource, so an unauthorized actor cannot enumerate which
resources exist.

## 4. Current User Resolution

- **Normal mode** (`DEV_AUTH_BYPASS=false`): `get_current_user()` requires an
  authenticated identity and returns **HTTP 401** otherwise. It never falls back
  to an arbitrary/default user.
- **Development mode** (`DEV_AUTH_BYPASS=true`): a fixed, deterministic
  development identity (`DEV_USER_ID`) is injected. This identity is stable
  across requests and test runs — no new identity is silently created per
  request — preserving the existing transformation and project test flow.
- Credentials and secrets are never exposed through either path.

## 5. Project Authorization

Every project operation (GET, UPDATE, DELETE, LIST) is scoped to the
authenticated user via `Project.user_id`. Cross-user project access returns 404
and does not leak the project name, metadata, owner identity, or timestamps.

## 6. Source Authorization

Standalone source operations (GET / DELETE) resolve authorization at the
database level through `get_source_owned()` which joins
`Source -> Project -> user`. Nested project operations first verify project
ownership. When both `project_id` and `source_id` are supplied (e.g. job
creation), the source is additionally verified to belong to the authorized
project. Cross-user source access returns 404 (anti-IDOR).

## 7. Transformation Authorization

Transformation jobs are project/user scoped. `get_job()` joins through the
owning project's `user_id` at the database level. Creating, reading, listing
history, retrieving outputs, cancelling, and re-running all require ownership.
A user cannot retrieve another user's job by guessing `transformation_job_id`.

## 8. Output Authorization

Outputs are never globally accessible by `output_id`. `get_output_owned()`
enforces the full chain `Output -> job -> project -> user` in a single SQL
query. This covers output metadata, content, generated artifact references,
listing, download, and export.

## 9. Artifact / Download Security

Downloads resolve the storage key exclusively from the **authorized** Output
record and its persisted metadata. The client never supplies a storage key or
filesystem path. Path traversal and arbitrary-filesystem access are prevented by
the storage adapter, which refuses keys that escape the configured storage root.
A cross-user artifact request returns 404.

## 10. Verification Result Authorization

Verification results inherit authorization from their parent output through the
same `Output -> job -> project -> user` chain. A user can never retrieve another
user's verification data by ID. Cross-user verification requests return 404.

## 11. RAG Authorization

RAG retrieval is project/user scoped. The retrieval service applies SQL-level
filters on `project_id` (and `source_id`) when provided, so the candidate pool
is restricted to the authorized project/source **before** any scoring occurs —
it never retrieves an unauthorized candidate for late Python-side filtering.

- If `project_id` is provided: retrieval is restricted to that project's chunks.
- If `source_id` is provided: retrieval is restricted to that source's chunks,
  and the caller must verify the source belongs to the requested project.
- Callers (e.g. the transformation worker) operate only on jobs already
  authorized when enqueued and pass the job's own project/source scope.

## 12. Worker Security Context

The transformation worker receives only the authoritative `job_id` that was
authorized when enqueued; it has no HTTP request context and trusts no payload
beyond the ID. `run_transformation_job()` now performs a defense-in-depth
**ownership-integrity check** before processing: it verifies the job resolves to
a project that owns a real user and that the job's source belongs to that same
project. A mismatched or orphaned relationship aborts the job as a
`TransformationError` instead of processing cross-tenant data.

## 13. Error Handling

- **401** — unauthenticated requests.
- **404** — unauthorized/unknown resource lookups (safe, no existence leak).
- **403** — used where explicit forbidden semantics are required.
- Errors never state that a resource "belongs to another account" or expose the
  owner's identity.

## 14. IDOR / BOLA Protections

- All object-level access goes through ownership-scoped service lookups.
- Client-supplied IDs are never trusted in isolation; they are always verified
  against the authenticated user's ownership chain.
- Random/nonexistent IDs return 404.
- Cross-user requests are indistinguishable from nonexistent-resource requests.

## 15. DEV_AUTH_BYPASS Behavior

Exactly as before Phase 9A: configurable via environment settings, requires no
real credentials in offline tests, is deterministic (stable dev identity), and
never exposes secrets. Production behavior never depends on `DEV_AUTH_BYPASS`
(which is forced off in staging/production).

## 16. Tests

`backend/tests/test_phase9a_authorization.py` proves both ALLOW (User A -> User A
resource) and DENY (User B -> User A resource) using two distinct users across
projects, sources, transformations, outputs, verification results, artifacts,
RAG isolation, worker integrity, IDOR, nonexistent-resource behavior, and
information-leakage checks, plus the existing DEV_AUTH_BYPASS transformation
flow.

## 17. Files Touched in Phase 9A

- `backend/app/services/source_service.py` — added `get_source_owned()`.
- `backend/app/services/transformation_service.py` — added `get_output_owned()`.
- `backend/app/api/v1/sources.py` — standalone source lookups now SQL-scoped.
- `backend/app/api/v1/transformations.py` — output/verification/export/download
  now use `get_output_owned()`.
- `backend/app/api/v1/content_intelligence.py` — source analysis uses
  `get_source_owned()`.
- `backend/app/transformation/service.py` — worker ownership-integrity check.
- `backend/tests/test_phase9a_authorization.py` — Phase 9A security test suite.
