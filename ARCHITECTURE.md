# System Architecture Document

## TransformIQ --- Gen AI Platform for Automated Content Transformation

**Problem Statement:** SIH 26154\
**Version:** 1.0\
**Status:** Proposed Architecture

------------------------------------------------------------------------

## 1. Architecture Objective

TransformIQ will use a modular, API-driven architecture that separates
source ingestion, content intelligence, retrieval, transformation
orchestration, output generation, verification and export.

The architecture is designed for:

-   Rapid SIH prototype development
-   AI-assisted development with IBM Bob
-   Independent team ownership
-   Docker-based local development
-   Cloud deployment
-   Future multimodal expansion
-   Maintainability and testability

The architecture deliberately avoids unnecessary microservices in the
MVP. Components should become independently deployable services only
when there is a clear operational benefit.

------------------------------------------------------------------------

## 2. High-Level Architecture

``` text
                         ┌─────────────────────┐
                         │       USER          │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │     FRONTEND        │
                         │ Transformation UI   │
                         └──────────┬──────────┘
                                    │ HTTPS
                                    ▼
                         ┌─────────────────────┐
                         │    BACKEND API      │
                         │ Authentication      │
                         │ Jobs / Projects     │
                         │ File APIs            │
                         └───────┬─────┬───────┘
                                 │     │
                    ┌────────────┘     └─────────────┐
                    ▼                                ▼
          ┌─────────────────┐              ┌─────────────────┐
          │   INGESTION     │              │   JOB/QUEUE     │
          │ PDF/DOCX/TEXT   │              │ Redis/Worker    │
          └────────┬────────┘              └────────┬────────┘
                   │                                │
                   ▼                                ▼
          ┌─────────────────┐              ┌─────────────────┐
          │    CONTENT      │              │   AI WORKERS    │
          │  INTELLIGENCE   │─────────────▶│                 │
          └────────┬────────┘              └────────┬────────┘
                   │                                │
                   ▼                                ▼
          ┌────────────────────────────────────────────────┐
          │          CANONICAL CONTENT MODEL               │
          └──────────────────────┬─────────────────────────┘
                                 │
                     ┌───────────┴────────────┐
                     │                        │
                     ▼                        ▼
             ┌──────────────┐        ┌─────────────────┐
             │ RAG / VECTOR │        │  TRANSFORMATION │
             │   STORAGE    │        │   ORCHESTRATOR  │
             └──────────────┘        └────────┬────────┘
                                              │
                  ┌───────────────┬───────────┼───────────────┐
                  ▼               ▼           ▼               ▼
              Summary         LinkedIn    Advisory       Presentation
                  │               │           │               │
                  └───────────────┴───────────┼───────────────┘
                                              ▼
                                   ┌─────────────────────┐
                                   │ QUALITY / VERIFY    │
                                   │ Grounding / Claims  │
                                   │ Consistency        │
                                   └──────────┬──────────┘
                                              │
                                              ▼
                                   ┌─────────────────────┐
                                   │ EXPORT / RESULTS    │
                                   └─────────────────────┘
```

------------------------------------------------------------------------

## 3. Architectural Layers

### Layer 1 --- Presentation

Responsible for:

-   Dashboard
-   Upload UI
-   Configuration controls
-   Output selection
-   Processing status
-   Results
-   Verification display
-   Export controls

The frontend must not contain AI/business logic.

------------------------------------------------------------------------

### Layer 2 --- API / Application

Responsible for:

-   Authentication/authorization
-   Request validation
-   Source/job management
-   API contracts
-   Configuration management
-   Result retrieval
-   Error handling

The API coordinates application workflows but should not become a
monolithic AI implementation.

------------------------------------------------------------------------

### Layer 3 --- Ingestion

Responsible for:

-   File validation
-   File metadata
-   PDF extraction
-   DOCX extraction
-   Text normalization
-   Future image/video ingestion
-   Source reference mapping

Conceptual flow:

``` text
Upload
 ↓
Validate
 ↓
Store original
 ↓
Extract
 ↓
Normalize
 ↓
Create source representation
```

------------------------------------------------------------------------

### Layer 4 --- Content Intelligence

Responsible for turning normalized content into structured information.

Outputs include:

``` text
metadata
summary
topics
entities
key_points
claims
statistics
dates
recommendations
source_references
```

Structured outputs should be schema validated.

------------------------------------------------------------------------

### Layer 5 --- Retrieval / RAG

Responsible for large-source retrieval.

``` text
Normalized Content
 ↓
Chunking
 ↓
Embeddings
 ↓
Vector Store
 ↓
Retriever
 ↓
Relevant Context
```

RAG should be used when needed rather than forcing every small request
through an unnecessarily complex retrieval pipeline.

------------------------------------------------------------------------

### Layer 6 --- Transformation Orchestrator

The orchestrator is the central AI workflow controller.

Input:

``` text
Canonical Content
+
User Configuration
+
Selected Output Types
```

Responsibilities:

-   Validate requested outputs
-   Select generators
-   Manage generation workflow
-   Track output jobs
-   Handle failures/retries
-   Trigger verification

The orchestrator should not contain the detailed prompt logic for every
output.

------------------------------------------------------------------------

### Layer 7 --- Output Generators

Each output should have an isolated generator/module.

``` text
transformations/
├── summary/
├── linkedin/
├── advisory/
├── presentation/
├── x/
├── infographic/
└── video/
```

Each generator receives structured content and configuration and returns
schema-validated output.

------------------------------------------------------------------------

### Layer 8 --- Quality / Verification

Responsible for:

-   Claim extraction
-   Source comparison
-   Grounding assessment
-   Cross-output consistency
-   Warnings

Verification results must be presented as AI-assisted checks, not
absolute truth guarantees.

------------------------------------------------------------------------

### Layer 9 --- Export

Responsible for converting structured results into usable artefacts.

Examples:

-   PDF
-   DOCX
-   PPTX
-   Image
-   Copyable text
-   Structured video package

------------------------------------------------------------------------

## 4. Recommended Technology Direction

The final technology choices should be confirmed in `TECH_STACK.md`, but
the architecture should support:

### Frontend

A modern React-based framework.

### Backend

Python-based API service such as FastAPI.

### AI orchestration

LangGraph or an equivalent explicit workflow/orchestration layer.

### Database

PostgreSQL.

### Vector retrieval

A PostgreSQL vector extension or dedicated vector database depending on
deployment constraints.

### Queue/cache

Redis.

### Storage

Object storage for uploaded and generated files.

### Containerization

Docker and Docker Compose.

### Cloud

Cloud provider selected based on available SIH/team resources.

The system should remain provider-agnostic at the application layer
where practical.

------------------------------------------------------------------------

## 5. Data Architecture

### Core entities

``` text
User
  │
  ├── Projects
  │      │
  │      └── Sources
  │             │
  │             └── Transformation Jobs
  │                    │
  │                    └── Outputs
  │                           │
  │                           └── Verification Results
```

### Storage responsibilities

**PostgreSQL** - Users - Projects - Sources metadata - Jobs - Outputs
metadata - Verification metadata

**Object storage** - Original uploads - Generated files - Rendered
artefacts

**Vector storage** - Document chunks - Embeddings - Retrieval metadata

**Redis** - Queue - Job state/cache where appropriate

------------------------------------------------------------------------

## 6. Asynchronous Processing

Long-running operations should not block normal HTTP requests.

Example:

``` text
POST /transform
       ↓
Create Job
       ↓
Queue Job
       ↓
Return job_id
       ↓
Worker processes
       ↓
Update status
       ↓
Frontend polls/receives status
       ↓
Results available
```

This is particularly important for:

-   Large documents
-   Multiple output generation
-   Presentation generation
-   Image/video processing
-   Future media rendering

------------------------------------------------------------------------

## 7. API Boundary

The frontend should communicate with the backend through explicit APIs.

Conceptual endpoints:

``` text
POST   /api/sources
GET    /api/sources/{id}

POST   /api/transformations
GET    /api/transformations/{id}

GET    /api/outputs/{id}
POST   /api/outputs/{id}/retry

GET    /api/verification/{id}

GET    /api/exports/{id}

GET    /api/health
```

Exact contracts should be defined before implementation.

------------------------------------------------------------------------

## 8. Canonical Content Contract

All output generators should consume a common schema.

Conceptual structure:

``` text
CanonicalContent
├── source_metadata
├── title
├── summary
├── topics[]
├── entities[]
├── key_points[]
├── claims[]
├── statistics[]
├── dates[]
├── recommendations[]
└── source_references[]
```

This is a critical architectural boundary.

It prevents each output agent from independently interpreting the
original document and helps maintain consistency.

------------------------------------------------------------------------

## 9. AI Prompt Architecture

Prompts should not be scattered throughout application code.

Recommended:

``` text
ai-engine/
├── prompts/
│   ├── content_intelligence/
│   ├── summary/
│   ├── linkedin/
│   ├── advisory/
│   ├── presentation/
│   └── verification/
```

Prompts should receive structured inputs and explicit constraints.

Generated outputs should be validated against schemas.

------------------------------------------------------------------------

## 10. Failure Handling

The architecture should support partial success.

Example:

``` text
Job
 ├── Summary        ✓
 ├── LinkedIn       ✓
 ├── Advisory       ✓
 └── Presentation   ✗
```

The system should retain successful results and allow the failed output
to be retried.

AI/API failures should have:

-   Timeout
-   Retry policy
-   Error classification
-   User-visible status

------------------------------------------------------------------------

## 11. Security Architecture

Security boundaries:

``` text
User
 ↓
Authentication
 ↓
Authorization
 ↓
API validation
 ↓
File validation
 ↓
Processing
 ↓
AI layer
```

Important principles:

-   Never expose secrets to the frontend.
-   Store secrets through environment/secret management.
-   Treat uploaded content as untrusted.
-   Do not allow document instructions to override system instructions.
-   Validate file types and sizes.
-   Restrict access to stored files.
-   Avoid sensitive content in logs.

------------------------------------------------------------------------

## 12. Multimodal Extension Architecture

The architecture should allow:

``` text
PDF ─────┐
DOCX ────┤
Text ────┤
Image ───┤
Video ───┘
          ↓
    Ingestion Adapters
          ↓
    Normalized Content
          ↓
 Canonical Content Model
```

Image and video processing should be added as adapters rather than
redesigning the downstream transformation engine.

------------------------------------------------------------------------

## 13. Docker Architecture

MVP development can use:

``` text
docker-compose.yml
```

Potential containers:

``` text
frontend
backend
worker
postgres
redis
vector-db (if separate)
```

AI providers can remain external services and should not require an LLM
container unless specifically needed.

The architecture should keep local development reproducible.

------------------------------------------------------------------------

## 14. Cloud Architecture

Target deployment:

``` text
                 Internet
                    │
                    ▼
             Load Balancer
                /       \
               ▼         ▼
          Frontend      API
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           Worker       PostgreSQL    Redis
              │
              ▼
        Object Storage
              │
              ▼
          AI Providers
```

Exact cloud services should be selected after evaluating available
credits, quotas, cost and SIH requirements.

------------------------------------------------------------------------

## 15. CI/CD Architecture

``` text
Developer
   ↓
Git Push / Pull Request
   ↓
Automated Tests
   ↓
Lint / Type Checks
   ↓
Docker Build
   ↓
Security Checks
   ↓
Container Registry
   ↓
Deployment
```

Production deployment should be separated from development environments.

------------------------------------------------------------------------

## 16. Observability

The system should expose:

-   Health endpoint
-   Structured application logs
-   Job status
-   Processing duration
-   AI failures
-   API failures
-   Worker failures

Future production additions:

-   Metrics
-   Tracing
-   Error tracking
-   Alerts

------------------------------------------------------------------------

## 17. Architectural Principles

1.  Build the MVP before advanced multimodal features.
2.  Prefer modularity over unnecessary microservices.
3.  Keep AI prompts and workflows separate from UI.
4.  Use typed/schema-validated contracts.
5.  Make long-running operations asynchronous.
6.  Maintain one canonical understanding of source content.
7.  Keep generated outputs independently retryable.
8.  Protect source data and secrets.
9.  Make components testable independently.
10. Keep deployment reproducible with Docker.
11. Avoid vendor lock-in where practical.
12. Human review remains important for sensitive communication.

------------------------------------------------------------------------

## 18. MVP Architecture Scope

The first working architecture should support:

``` text
Text / PDF / DOCX
        ↓
Ingestion
        ↓
Content Intelligence
        ↓
Canonical Content
        ↓
RAG where needed
        ↓
Transformation Orchestrator
        ↓
Summary / LinkedIn / Advisory / Presentation
        ↓
Verification
        ↓
Export
```

Image, video and advanced output rendering should be added only after
this pipeline is stable.

------------------------------------------------------------------------

## 19. Architecture Acceptance Criteria

The architecture is ready for implementation when:

-   All major PRD requirements map to an architectural component.
-   Input/output boundaries are defined.
-   Canonical Content schema is defined.
-   AI orchestration boundary is defined.
-   Database/storage responsibilities are defined.
-   Async job architecture is defined.
-   Security boundaries are defined.
-   Docker deployment boundaries are defined.
-   Cloud deployment direction is defined.
-   Team ownership can be mapped to components.
-   The architecture does not introduce unnecessary complexity for the
    SIH prototype.
