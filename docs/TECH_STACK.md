# TECH_STACK.md

## TransformIQ — Gen AI Platform for Automated Content Transformation

**SIH Problem Statement:** 26154  
**Version:** 1.0  
**Status:** Approved for MVP planning

---

## 1. Purpose

This document defines the approved technology stack for TransformIQ.

The stack is optimized for SIH 2026 prototype delivery, rapid AI-assisted/vibe-coded development, IBM Bob compatibility, six-member team capabilities, simple local development, Docker-based deployment, cloud portability, maintainability, AI/RAG capabilities, and reliable demonstration.

The team should not introduce additional technologies without a clear requirement.

---

## 2. Technology Selection Principles

1. Prefer mature and well-documented technologies.
2. Prefer technologies that IBM Bob can scaffold and maintain effectively.
3. Minimize the number of independent infrastructure components.
4. Prefer one database over multiple databases where practical.
5. Keep AI providers replaceable.
6. Keep business logic independent from frontend code.
7. Use typed/schema-validated contracts between AI components.
8. Use asynchronous processing for long-running jobs.
9. Containerize the application with Docker.
10. Optimize for a reliable SIH demonstration rather than architectural complexity.

---

## 3. Approved Stack

| Layer | Technology | Status |
|---|---|---|
| Frontend framework | Next.js + React | Approved |
| Frontend language | TypeScript | Approved |
| UI styling | Tailwind CSS | Approved |
| UI components | shadcn/ui | Approved |
| Backend language | Python | Approved |
| Backend framework | FastAPI | Approved |
| AI orchestration | LangGraph | Approved |
| LLM integration | Provider-agnostic adapter | Approved |
| Database | PostgreSQL | Approved |
| Vector search | pgvector | Approved |
| Background jobs | Redis + Worker | Approved |
| File storage | Object storage through storage adapter | Approved |
| Document processing | Python document-processing libraries | Approved |
| Presentation generation | PPTX generation library | Approved |
| Containerization | Docker + Docker Compose | Approved |
| Version control | Git + GitHub | Approved |
| CI/CD | GitHub Actions | Approved |
| Backend testing | pytest | Approved |
| Frontend testing | TypeScript/React testing tools | Approved |
| Cloud provider | To be finalized during deployment design | Pending |

---

## 4. Frontend

### Next.js + React + TypeScript

Responsibilities:
- Transformation dashboard
- Source upload
- Configuration controls
- Output selection
- Job status
- Results display
- Verification display
- Export controls

TypeScript is mandatory for frontend application code. Avoid unnecessary use of `any`.

Suggested component organization:

```text
components/
├── upload/
├── configuration/
├── output-selection/
├── results/
├── verification/
├── export/
└── common/
```

---

## 5. UI and Styling

### Tailwind CSS
Used for rapid, responsive and consistent styling.

### shadcn/ui
Used for reusable UI components such as buttons, cards, dialogs, tabs, forms, alerts, tables and progress indicators.

Avoid multiple overlapping UI component libraries unless a real requirement appears.

---

## 6. Backend

### Python + FastAPI

FastAPI responsibilities:
- API endpoints
- Request validation
- Authentication/authorization integration
- Source management
- Transformation job creation
- Job status
- Output retrieval
- Verification results
- Export access
- Health checks

Backend APIs should use explicit request/response schemas.

---

## 7. AI Architecture

### LangGraph

LangGraph will manage the core AI workflow:

```text
Source
  ↓
Ingestion
  ↓
Content Intelligence
  ↓
Canonical Content
  ↓
Retrieval when required
  ↓
Transformation
  ↓
Verification
  ↓
Result
```

Do not create a large number of independent agents without a demonstrated need.

---

## 8. LLM Provider Strategy

Use an abstraction layer:

```text
Application
     ↓
LLM Provider Interface
     ↓
Provider Adapter
     ↓
Selected LLM
```

Requirements:
- API keys never exposed to frontend.
- Secrets supplied through environment/secret management.
- Model names configurable.
- Prompts not tightly coupled to one provider.
- Provider switching should require minimal application changes.

Final model/provider will be selected after testing quality, latency, cost, quota and availability.

---

## 9. Structured AI Output

LLM outputs should be schema validated wherever possible.

Examples:
- CanonicalContent
- TransformationOutput
- PresentationStructure
- VerificationResult

Invalid model output must be detected and retried/repaired where appropriate, or rejected with a controlled error.

---

## 10. RAG

### PostgreSQL + pgvector

PostgreSQL will provide vector storage through pgvector for the MVP.

RAG flow:

```text
Source
 ↓
Text extraction
 ↓
Chunking
 ↓
Embedding generation
 ↓
PostgreSQL + pgvector
 ↓
Similarity retrieval
 ↓
Relevant context
 ↓
LLM
```

Use RAG when it improves source-grounded generation, particularly for larger documents.

---

## 11. Database

### PostgreSQL

Primary relational database for:
- Users
- Projects
- Sources
- Transformation Jobs
- Outputs
- Verification Results
- Metadata

The schema will be defined separately in `API_DATABASE_DESIGN.md`.

---

## 12. Background Processing

### Redis + Worker

Long-running operations should be asynchronous.

Examples:
- Document processing
- Embedding generation
- Large-document analysis
- Multiple-output generation
- Presentation generation
- Future image/video processing

Flow:

```text
Frontend
   ↓
FastAPI
   ↓
Create Job
   ↓
Redis
   ↓
Worker
   ↓
AI Processing
   ↓
Database / Storage
   ↓
Frontend retrieves status/results
```

---

## 13. File Storage

Use object storage through a storage abstraction such as `StorageService`.

Potential stored objects:
- Original PDF/DOCX
- Generated PDF/DOCX
- Generated PPTX
- Generated infographic
- Future media packages

Store metadata and storage references in PostgreSQL rather than large binary files.

---

## 14. Document Processing

MVP inputs:
- PDF
- DOCX
- TXT/direct text

Use established Python libraries for deterministic extraction and normalization before LLM reasoning.

Flow:

```text
File
 ↓
Validation
 ↓
Extraction
 ↓
Cleaning
 ↓
Normalization
 ↓
Canonical Content processing
```

---

## 15. Presentation Generation

Use a two-stage approach:

```text
Source
 ↓
LLM
 ↓
Structured Presentation JSON
 ↓
PPTX Generator
 ↓
.pptx
```

The LLM generates slide structure, content, speaker notes and visual recommendations. The application creates the actual PowerPoint file.

---

## 16. Output Generation

Isolate output generators:

```text
transformations/
├── summary/
├── linkedin/
├── advisory/
├── presentation/
├── x/
├── infographic/
└── video/
```

MVP priority:
- summary
- linkedin
- advisory
- presentation

Advanced modules come after the MVP pipeline is stable.

---

## 17. Verification

The verification layer supports:
- Claim extraction
- Source matching
- Grounding checks
- Cross-output consistency
- Warning generation

Verification is an AI-assisted quality mechanism and must not be represented as a guarantee of factual correctness.

---

## 18. Testing

### Backend
Use pytest for unit, API, processing, database integration, transformation and verification tests.

### Frontend
Use appropriate TypeScript/React testing tools for components, forms, API integration and workflows.

### AI evaluation
Create a fixed evaluation dataset containing representative sources and expected important facts. Evaluate required fields, important facts, grounding, structure and consistency.

---

## 19. Docker

Docker is mandatory for reproducible development and deployment.

Expected local services:

```text
frontend
backend
worker
postgres
redis
```

External AI providers and cloud object storage do not need to be containerized.

---

## 20. Environment Configuration

Use environment variables/secrets.

Example categories:

```text
DATABASE_URL
REDIS_URL
LLM_API_KEY
LLM_MODEL
STORAGE_ENDPOINT
STORAGE_BUCKET
AUTH_SECRET
```

Never commit real secret values. Provide `.env.example`.

---

## 21. Git and GitHub

GitHub is the source-control platform.

Recommended workflow:

```text
main
 │
 ├── feature/frontend
 ├── feature/backend
 ├── feature/ai
 ├── feature/rag
 └── feature/deployment
```

Feature branches should preferably be tested before merging. `main` should remain runnable.

---

## 22. CI/CD

GitHub Actions pipeline:

```text
Push / Pull Request
        ↓
Lint
        ↓
Tests
        ↓
Build
        ↓
Docker Build
        ↓
Deployment
```

CI should fail when essential tests or builds fail.

---

## 23. Cloud

The cloud provider is intentionally not hard-coded yet.

Final selection will consider:
- Available credits
- Free-tier limits
- SIH requirements
- Docker support
- PostgreSQL support
- Redis support
- Object storage
- Deployment simplicity
- Team familiarity
- Reliability

The application must remain portable.

---

## 24. Technologies Explicitly Avoided for MVP

Unless a concrete requirement appears, do not introduce:
- Kubernetes
- Kafka
- Multiple relational databases
- Multiple vector databases
- Custom foundation-model training
- Complex multi-agent swarms
- Unnecessary microservices
- Multiple frontend frameworks
- Multiple UI component libraries
- Self-hosted LLM infrastructure without a clear need

The objective is a reliable working system, not maximum architectural complexity.

---

## 25. IBM Bob Development Constraints

IBM Bob must:

1. Read `PRD.md` before implementation.
2. Read `ARCHITECTURE.md` before implementation.
3. Read `TECH_STACK.md` before implementation.
4. Follow the approved stack unless explicitly instructed otherwise.
5. Avoid adding dependencies without justification.
6. Avoid replacing approved technologies automatically.
7. Implement one phase at a time.
8. Run tests after meaningful changes.
9. Keep the application runnable after each phase.
10. Explain major architectural deviations before making them.
11. Never hard-code secrets.
12. Keep AI providers configurable.
13. Generate schema-validated AI outputs.
14. Preserve existing working functionality when adding features.

---

## 26. Technology Decision Summary

```text
Frontend:
Next.js + React + TypeScript

UI:
Tailwind CSS + shadcn/ui

Backend:
Python + FastAPI

AI Workflow:
LangGraph

LLM:
Provider-agnostic adapter

Database:
PostgreSQL

Vector Search:
pgvector

Background Processing:
Redis + Worker

Storage:
Object Storage + Storage Adapter

Documents:
Python extraction libraries

Presentation:
PPTX generation library

Testing:
pytest + TypeScript/React testing tools

Containers:
Docker + Docker Compose

Source Control:
Git + GitHub

CI/CD:
GitHub Actions

Cloud:
To be finalized
```

---

## 27. Definition of Done

The technology stack is approved when:
- Each PRD capability has a supporting technology.
- No major component has an unnecessary duplicate technology.
- The team can reasonably learn/debug the stack.
- IBM Bob can scaffold and maintain it.
- Docker can reproduce the development environment.
- The architecture can be deployed to cloud infrastructure.
- AI providers can be replaced without rewriting the application.
- The stack supports the MVP before advanced features.
