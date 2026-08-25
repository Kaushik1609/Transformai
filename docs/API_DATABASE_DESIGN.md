# API_DATABASE_DESIGN.md

## TransformIQ — Gen AI Platform for Automated Content Transformation

**SIH Problem Statement:** 26154  
**Version:** 1.0  
**Status:** MVP Design

---

# 1. Purpose

This document defines the application data model, API contracts, job lifecycle, storage references and service boundaries.

The design is intentionally simple enough for AI-assisted/vibe-coded implementation while remaining scalable for the SIH prototype.

---

# 2. High-Level Request Flow

```text
User
 ↓
Next.js Frontend
 ↓
FastAPI API
 ↓
Create Transformation Job
 ↓
Redis / Worker
 ↓
Ingestion
 ↓
Content Intelligence
 ↓
RAG when required
 ↓
Transformation Generator(s)
 ↓
Verification
 ↓
PostgreSQL + Object Storage
 ↓
Frontend polls/subscribes for status
 ↓
User downloads/views outputs
```

---

# 3. Core Entities

```text
User
 └── Project
      ├── Source
      │    └── SourceChunk
      ├── TransformationJob
      │    └── Output
      │         └── VerificationResult
      └── GenerationConfiguration
```

---

# 4. Database

## 4.1 users

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| email | VARCHAR | Unique |
| name | VARCHAR | Display name |
| role | VARCHAR | operator/admin |
| created_at | TIMESTAMP | Required |
| updated_at | TIMESTAMP | Required |

---

## 4.2 projects

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK users.id |
| name | VARCHAR | Project name |
| description | TEXT | Optional |
| created_at | TIMESTAMP | Required |
| updated_at | TIMESTAMP | Required |

---

## 4.3 sources

Represents uploaded or directly submitted source material.

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| project_id | UUID | FK |
| source_type | VARCHAR | text/pdf/docx/image/video/url |
| original_filename | VARCHAR | Nullable for direct text |
| storage_key | VARCHAR | Nullable for direct text |
| extracted_text | TEXT | Normalized source text |
| mime_type | VARCHAR | Optional |
| file_size | BIGINT | Optional |
| language | VARCHAR | Default en |
| status | VARCHAR | uploaded/processing/ready/failed |
| metadata | JSONB | Flexible metadata |
| created_at | TIMESTAMP | Required |

For very large content, extracted text may be stored in object storage with a reference in the database.

---

## 4.4 source_chunks

Used for RAG.

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| source_id | UUID | FK |
| chunk_index | INTEGER | Ordering |
| content | TEXT | Chunk text |
| embedding | VECTOR | pgvector |
| metadata | JSONB | Page/section/etc. |
| created_at | TIMESTAMP | Required |

---

## 4.5 generation_configurations

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| project_id | UUID | FK |
| target_audience | VARCHAR | Optional |
| tone | VARCHAR | Optional |
| language | VARCHAR | Default English |
| detail_level | VARCHAR | concise/standard/detailed |
| communication_objective | VARCHAR | Optional |
| content_style | VARCHAR | Optional |
| custom_instructions | TEXT | Optional |
| created_at | TIMESTAMP | Required |

---

## 4.6 transformation_jobs

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| project_id | UUID | FK |
| source_id | UUID | FK |
| configuration_id | UUID | FK |
| requested_outputs | JSONB | Selected output types |
| status | VARCHAR | queued/running/completed/failed |
| progress | INTEGER | 0-100 |
| error_message | TEXT | Nullable |
| started_at | TIMESTAMP | Nullable |
| completed_at | TIMESTAMP | Nullable |
| created_at | TIMESTAMP | Required |

---

## 4.7 outputs

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| job_id | UUID | FK |
| output_type | VARCHAR | summary/linkedin/x/advisory/infographic/presentation/video |
| status | VARCHAR | generating/completed/failed |
| structured_content | JSONB | AI-generated structured result |
| text_content | TEXT | Optional rendered text |
| storage_key | VARCHAR | Optional generated file |
| mime_type | VARCHAR | Optional |
| metadata | JSONB | Optional |
| created_at | TIMESTAMP | Required |

---

## 4.8 verification_results

| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| output_id | UUID | FK |
| overall_status | VARCHAR | passed/warning/failed |
| grounding_score | NUMERIC | Optional |
| consistency_score | NUMERIC | Optional |
| claims_checked | INTEGER | Optional |
| claims_supported | INTEGER | Optional |
| warnings | JSONB | Verification warnings |
| details | JSONB | Detailed evidence |
| created_at | TIMESTAMP | Required |

Scores are internal quality indicators, not guarantees of factual accuracy.

---

# 5. Relationships

```text
users 1 ─── N projects

projects 1 ─── N sources

sources 1 ─── N source_chunks

projects 1 ─── N generation_configurations

projects 1 ─── N transformation_jobs

sources 1 ─── N transformation_jobs

generation_configurations 1 ─── N transformation_jobs

transformation_jobs 1 ─── N outputs

outputs 1 ─── N verification_results
```

---

# 6. API Conventions

Base path:

```text
/api/v1
```

Responses should use JSON unless downloading a file.

Common response structure:

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

Error example:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request"
  }
}
```

Use appropriate HTTP status codes.

---

# 7. Authentication APIs

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

For the SIH MVP, authentication may initially be simplified if the evaluation environment does not require multi-user access. The security boundary must still be designed so authentication can be enabled.

---

# 8. Project APIs

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
DELETE /api/v1/projects/{project_id}
```

---

# 9. Source APIs

```text
POST /api/v1/projects/{project_id}/sources
GET  /api/v1/projects/{project_id}/sources
GET  /api/v1/sources/{source_id}
DELETE /api/v1/sources/{source_id}
```

Upload endpoint should support multipart file upload.

Direct text can be accepted through JSON.

---

# 10. Transformation API

## Create job

```text
POST /api/v1/transformations
```

Example request:

```json
{
  "project_id": "uuid",
  "source_id": "uuid",
  "output_types": [
    "summary",
    "linkedin",
    "presentation"
  ],
  "configuration": {
    "target_audience": "technology executives",
    "tone": "professional",
    "language": "English",
    "detail_level": "standard",
    "communication_objective": "inform"
  }
}
```

Response:

```json
{
  "success": true,
  "data": {
    "job_id": "uuid",
    "status": "queued"
  }
}
```

---

# 11. Job APIs

```text
GET /api/v1/transformations/{job_id}
GET /api/v1/transformations/{job_id}/outputs
POST /api/v1/transformations/{job_id}/cancel
```

Status:

```text
queued
running
completed
failed
cancelled
```

---

# 12. Output APIs

```text
GET /api/v1/outputs/{output_id}
GET /api/v1/outputs/{output_id}/verification
GET /api/v1/outputs/{output_id}/download
```

The download endpoint should return a signed/temporary storage URL or stream the file securely.

---

# 13. Verification API

```text
POST /api/v1/outputs/{output_id}/verify
GET  /api/v1/outputs/{output_id}/verification
```

Verification should be automatically triggered after generation for supported output types.

Manual re-verification can be supported through the POST endpoint.

---

# 14. Health APIs

```text
GET /health
GET /ready
```

`/health` confirms the process is alive.

`/ready` confirms required dependencies are available.

---

# 15. Output Type Enum

Initial supported values:

```text
summary
linkedin
x
advisory
infographic
presentation
video
```

MVP implementation priority:

```text
1. summary
2. linkedin
3. advisory
4. presentation
5. x
6. infographic
7. video
```

The API should support multiple output types in one job.

---

# 16. Job State Machine

```text
QUEUED
  ↓
RUNNING
  ↓
PROCESSING_SOURCE
  ↓
ANALYZING
  ↓
RETRIEVING_CONTEXT
  ↓
GENERATING
  ↓
VERIFYING
  ↓
COMPLETED
```

Failure can occur at any stage:

```text
ANY STATE → FAILED
```

The system should preserve a useful error message and allow retry where safe.

---

# 17. Redis Job Payload

Conceptual payload:

```json
{
  "job_id": "uuid",
  "project_id": "uuid",
  "source_id": "uuid",
  "output_types": ["summary", "presentation"],
  "configuration_id": "uuid"
}
```

The worker must retrieve authoritative data from PostgreSQL rather than trusting arbitrary client-supplied job data.

---

# 18. Storage Keys

Recommended structure:

```text
projects/{project_id}/sources/{source_id}/original.ext

projects/{project_id}/jobs/{job_id}/outputs/{output_id}/result.ext
```

Do not expose internal storage credentials.

---

# 19. Security Requirements

- Validate file type and size.
- Sanitize filenames.
- Never expose API keys.
- Validate all API input.
- Authorize access to project/source/output resources.
- Do not trust client-provided user IDs.
- Restrict generated download URLs.
- Apply upload limits.
- Log security-relevant failures without logging secrets.
- Keep secrets outside Git.

---

# 20. API Design Rules for IBM Bob

IBM Bob must:
- Implement schemas before endpoints.
- Keep API routes versioned.
- Keep business logic out of route handlers.
- Use service modules.
- Validate request and response data.
- Return predictable errors.
- Avoid breaking existing endpoints.
- Add tests for every major endpoint.
