# DEVELOPMENT_PLAN.md

## TransformIQ — Gen AI Platform for Automated Content Transformation

**SIH Problem Statement:** 26154  
**Version:** 1.0  
**Status:** Approved Development Roadmap

---

# 1. Development Philosophy

This project will be developed primarily through AI-assisted/vibe coding using IBM Bob.

The team will provide:
- Product requirements
- Architecture constraints
- Technology decisions
- Prompts
- Reviews
- Testing
- Debugging
- Deployment knowledge

IBM Bob will generate and modify much of the implementation.

Core rule:

> Never ask the AI IDE to build the entire product in one prompt.

Build in small, testable phases while keeping the application runnable.

---

# 2. Team Structure

## Member 1 — Frontend
Dashboard, source upload, configuration UI.

## Member 2 — Frontend
Results, verification, export UI, frontend integration/testing.

## Member 3 — Backend
FastAPI, database, APIs, authentication.

## Member 4 — Backend
Workers, storage, job processing, backend testing.

## Member 5 — ML/AI
Prompting, LangGraph, RAG, generation pipelines.

## Member 6 — ML/AI
Verification, evaluation, AI quality and output generators.

## Deployment/Integration Lead
The member with Docker/cloud knowledge coordinates:
- Docker
- Environment configuration
- CI/CD
- Cloud deployment
- Integration
- Release management

All members should still be able to run the project locally.

---

# 3. Development Phases

```text
PHASE 0  Repository + Environment
PHASE 1  Application Scaffold
PHASE 2  Database + API Foundation
PHASE 3  Source Ingestion
PHASE 4  AI Content Intelligence
PHASE 5  RAG
PHASE 6  Transformation Engine
PHASE 7  Output Generators
PHASE 8  Verification
PHASE 9  Frontend Integration
PHASE 10 Export + Polish
PHASE 11 Testing + Evaluation
PHASE 12 Docker + Cloud Deployment
PHASE 13 SIH Demo Hardening
```

---

# 4. Phase 0 — Repository and Environment

### Objectives

Create the clean repository.

Expected structure:

```text
transformiq/
├── frontend/
├── backend/
├── worker/
├── docs/
├── tests/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── LICENSE
```

Also establish:
- Git
- GitHub
- Branch strategy
- Environment variables
- Docker baseline

### Exit criteria

- Repository created.
- README exists.
- No secrets committed.
- Docker baseline starts successfully.
- Team can clone and run the project.

---

# 5. Phase 1 — Application Scaffold

### Frontend

Create:
- Next.js
- React
- TypeScript
- Tailwind
- shadcn/ui
- Base dashboard layout

### Backend

Create:
- FastAPI
- Configuration module
- Health endpoints
- API versioning
- Error handling
- Logging

### Worker

Create:
- Worker process
- Redis connection
- Basic test job

### Exit criteria

```text
Frontend → Backend → Health API
Backend → Redis
Backend → PostgreSQL
Worker → Redis
```

all work.

---

# 6. Phase 2 — Database + API Foundation

Implement:
- SQLAlchemy/database layer or approved PostgreSQL ORM approach
- Migrations
- Users
- Projects
- Sources
- Configurations
- Jobs
- Outputs
- Verification results

Implement basic CRUD APIs.

### Exit criteria

- Database migrations run.
- Tables created.
- API schemas validated.
- CRUD tests pass.
- No hard-coded database credentials.

---

# 7. Phase 3 — Source Ingestion

Implement:

```text
TXT
PDF
DOCX
Direct text
```

Pipeline:

```text
Upload
 ↓
Validation
 ↓
Storage
 ↓
Extraction
 ↓
Cleaning
 ↓
Normalization
 ↓
Source READY
```

Add:
- File-size limits
- MIME validation
- Error handling
- Metadata

### Exit criteria

A user can upload a supported document and see its processing status become `ready`.

---

# 8. Phase 4 — Content Intelligence

Create the canonical content representation.

Conceptual structure:

```text
CanonicalContent
├── title
├── summary
├── entities
├── key_facts
├── dates
├── statistics
├── claims
├── topics
├── source_references
└── metadata
```

The exact schema will be implemented and validated before generation.

### Exit criteria

The same source produces structured canonical content that can be reused by multiple output generators.

---

# 9. Phase 5 — RAG

Implement:

```text
Source
 ↓
Chunking
 ↓
Embedding
 ↓
pgvector
 ↓
Similarity Retrieval
 ↓
Context
```

Add retrieval only where useful.

### Exit criteria

A test document can be indexed and relevant chunks can be retrieved for a query.

---

# 10. Phase 6 — Transformation Engine

Implement the LangGraph workflow:

```text
Input
 ↓
Analyze
 ↓
Canonical Content
 ↓
Retrieve if required
 ↓
Generate
 ↓
Validate
 ↓
Verify
```

Implement multi-output support.

Example:

```text
One source
   ↓
┌── Summary
├── LinkedIn
├── Advisory
└── Presentation
```

### Exit criteria

One job can generate multiple selected output types from the same source.

---

# 11. Phase 7 — Output Generators

Implement in priority order.

## Generator 1 — Executive Summary

Produces concise structured/text output.

## Generator 2 — LinkedIn Post

Produces publication-ready professional content.

## Generator 3 — Advisory

Produces structured advisory content.

## Generator 4 — Presentation

Produces:
- Slide structure
- Slide content
- Speaker notes
- Visual recommendations
- Actual PPTX

## Generator 5 — X/Twitter

Produces platform-optimized post/thread structure.

## Generator 6 — Infographic

Produces:
- Key messages
- Sections
- Layout recommendation
- Visual suggestions

## Generator 7 — Video

Produces a complete video package:
- Script
- Storyboard
- Scene descriptions
- Narration
- Subtitles
- Visual recommendations

### Important

If actual automated video rendering becomes unreliable or time-consuming, the MVP should still provide the complete video package specified by the PS rather than destabilizing the core system.

---

# 12. Phase 8 — Verification

Verification should run after generation.

Checks:

```text
Source
 ↓
Claims
 ↓
Generated Output
 ↓
Evidence Matching
 ↓
Consistency
 ↓
Warnings
```

Display:
- Passed checks
- Warnings
- Unsupported claims
- Evidence references

### Exit criteria

A deliberately altered generated claim can be detected or flagged in evaluation tests.

---

# 13. Phase 9 — Frontend Integration

Dashboard workflow:

```text
1. Create/select project
2. Upload source
3. Configure audience/tone/language/detail
4. Select outputs
5. Generate
6. View progress
7. View outputs
8. View verification
9. Download/export
```

Important UI states:

```text
Idle
Uploading
Processing
Generating
Verifying
Completed
Failed
```

The UI must never appear frozen during long-running jobs.

---

# 14. Phase 10 — Export + Polish

Add:
- Download buttons
- Copy-to-clipboard
- File export
- Presentation download
- Output history
- Clear error messages
- Responsive dashboard
- Loading states
- Empty states

Polish only after the core pipeline is stable.

---

# 15. Phase 11 — Testing and Evaluation

## Software tests

Test:
- API
- Database
- Uploads
- Workers
- Output generation
- Verification
- Frontend workflows

## AI evaluation

Create at least 5–10 representative source documents covering:
- News
- Report
- Advisory
- Policy
- Incident
- Research-style content

For each, define important facts that must survive transformation.

Evaluate:
- Relevance
- Grounding
- Completeness
- Format compliance
- Consistency
- Hallucination/warning behavior

---

# 16. Phase 12 — Docker and Deployment

Local target:

```text
docker compose up
```

Services:

```text
frontend
backend
worker
postgres
redis
```

Then:

```text
GitHub
 ↓
CI
 ↓
Docker Build
 ↓
Cloud
```

Cloud provider is selected after checking current credits, service availability and deployment constraints.

---

# 17. Phase 13 — SIH Demo Hardening

Before demo:

- Freeze core features.
- Test the exact demo source.
- Prepare backup source.
- Test internet/API failures.
- Confirm environment variables.
- Confirm cloud deployment.
- Test every selected output.
- Test downloads.
- Test verification warnings.
- Remove development-only UI.
- Ensure no secrets are visible.
- Record demo fallback screenshots/video if needed.

---

# 18. MVP Definition

The MVP is successful if an operator can:

```text
Upload source
      ↓
Configure generation
      ↓
Select multiple outputs
      ↓
Generate
      ↓
Verify
      ↓
View/download results
```

At minimum, the demo should reliably support:

- Source text/document ingestion
- Executive Summary
- LinkedIn Post
- Advisory
- Presentation
- Multiple outputs from one source
- Audience/tone/language/detail controls
- Source-grounded generation
- Verification
- Export/download

---

# 19. Advanced Features

Only implement after MVP stability:

- Image understanding
- Video input
- Actual automated video rendering
- Advanced infographic rendering
- More output types
- Multi-language expansion
- Advanced analytics
- Team collaboration
- Scheduling
- Version comparison

---

# 20. IBM Bob Prompting Strategy

IBM Bob should receive prompts in this sequence:

```text
1. Context
2. Relevant documentation
3. Exact phase
4. Exact task
5. Constraints
6. Acceptance criteria
7. Testing requirement
8. Expected output
```

Do not use vague prompts such as:

> "Build the whole project."

Prefer:

> "Read PRD.md, ARCHITECTURE.md and TECH_STACK.md. Implement Phase 2 database foundation only. Do not modify frontend behavior. Create migrations, models, schemas and tests. Run the relevant tests and report failures."

---

# 21. Vibe Coding Rules

1. Never blindly accept generated code.
2. Inspect diffs.
3. Run the application after major changes.
4. Run tests after major changes.
5. Commit working milestones.
6. Keep prompts scoped.
7. Never let the AI silently change architecture.
8. Never paste real API keys into prompts.
9. Ask Bob to explain unfamiliar generated code when necessary.
10. Fix root causes rather than stacking patches.
11. Keep `main` runnable.
12. Back up working versions with Git tags/commits.

---

# 22. Git Milestones

Suggested milestones:

```text
v0.1-scaffold
v0.2-api-db
v0.3-ingestion
v0.4-content-intelligence
v0.5-rag
v0.6-transformations
v0.7-verification
v0.8-frontend
v0.9-export
v1.0-sih-mvp
```

---

# 23. Definition of Done per Phase

Every phase is complete only when:

- Code exists.
- Relevant tests exist.
- Tests pass.
- Existing functionality still works.
- No secrets are committed.
- Documentation is updated where necessary.
- Changes are committed to Git.
- The next phase can start without unresolved architectural blockers.

---

# 24. Final Build Order

```text
PRD.md                         ✅
ARCHITECTURE.md                ✅
TECH_STACK.md                  ✅
API_DATABASE_DESIGN.md         ✅
DEVELOPMENT_PLAN.md            ✅
        ↓
FINAL DOCUMENT REVIEW
        ↓
IBM BOB
        ↓
PHASE 0
        ↓
PHASE 1
        ↓
PHASE 2
        ↓
...
        ↓
SIH MVP
```

---

# 25. Critical Rule

Do not start advanced media features before the core transformation pipeline is reliable.

The winning demo should demonstrate:

> **One source → configurable intelligence → multiple high-quality deliverables → verification → export.**

Reliability and demonstrable PS alignment take priority over feature count.
