# TransformIQ

**Gen AI Platform for Automated Content Transformation**
Enterprise AI Content Transformation Platform

---

## Overview

TransformIQ converts source documents (text, PDF, DOCX) into multiple audience-specific communication artefacts through a single configurable AI pipeline.

**Core workflow:**

```
Source → Content Intelligence → Canonical Content → Configurable Transformation → Multiple Outputs → Verification → Export
```

**MVP outputs:** Executive Summary · LinkedIn Post · Advisory · Presentation

---

## Repository Structure

```
.
├── frontend/          # Next.js + React + TypeScript + Tailwind + shadcn/ui
├── backend/           # Python + FastAPI (API layer)
├── worker/            # Python + RQ (background job processor)
├── docs/              # Project specification documents
├── tests/             # Top-level test utilities and integration tests
├── docker-compose.yml # Local development orchestration
├── .env.example       # Environment variable template
└── README.md
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + React + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Backend | Python + FastAPI |
| AI Orchestration | LangGraph |
| Database | PostgreSQL + pgvector |
| Background Jobs | Redis + RQ |
| Storage | Local filesystem (dev) / S3-compatible (prod) |
| Containerization | Docker + Docker Compose |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Node.js 20+](https://nodejs.org/) (for local frontend development without Docker)
- [Python 3.11+](https://www.python.org/) (for local backend development without Docker)
- [Git](https://git-scm.com/)

---

## Quick Start (Docker Compose)

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-root>
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and fill in your values. At minimum, set `LLM_API_KEY` for AI features (not required for Phase 0).

### 3. Start all services

```bash
docker compose up --build
```

Services started:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health
- **Ready**: http://localhost:8000/ready
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### 4. Stop services

```bash
docker compose down
```

To also remove volumes (database data):

```bash
docker compose down -v
```

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp ../.env.example .env   # adjust DATABASE_URL/REDIS_URL to localhost
uvicorn app.main:app --reload --port 8000
```

### Worker

```bash
cd worker
# Activate the same venv or create a separate one
pip install -r requirements.txt
python worker.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Running Tests

### Backend

```bash
cd backend
pip install -r requirements.txt
pytest
```

### Frontend

```bash
cd frontend
npm install
npm test
```

---

## Branch Strategy

```
main                  # Always runnable — protected
 ├── feature/frontend
 ├── feature/backend
 ├── feature/ai
 ├── feature/rag
 └── feature/deployment
```

- Feature branches are merged to `main` only after tests pass.
- `main` must remain runnable at all times.

---

## Development Phases

| Phase | Description |
|---|---|
| 0 | Repository + Environment (current) |
| 1 | Application Scaffold |
| 2 | Database + API Foundation |
| 3 | Source Ingestion |
| 4 | Content Intelligence |
| 5 | RAG |
| 6 | Transformation Engine |
| 7 | Output Generators |
| 8 | Verification |
| 9 | Frontend Integration |
| 10 | Export + Polish |
| 11 | Testing + Evaluation |
| 12 | Docker + Cloud Deployment |
| 13 | Evaluation Demo Hardening |

---

## Team Ownership

| Member | Area |
|---|---|
| Frontend 1 | Transformation workspace, upload, configuration UI |
| Frontend 2 | Results, verification, export UI |
| Backend 1 | FastAPI, database, APIs, authentication |
| Backend 2 | Workers, storage, job processing |
| AI/ML 1 | Content Intelligence, LangGraph, RAG |
| AI/ML 2 | Verification, output generators, AI evaluation |
| Deployment Lead | Docker, cloud, CI/CD, integration |

---

## Specification Documents

| Document | Description |
|---|---|
| [PRD.md](PRD.md) | Product Requirements Document |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System Architecture |
| [TECH_STACK.md](TECH_STACK.md) | Approved Technology Stack |
| [API_DATABASE_DESIGN.md](API_DATABASE_DESIGN.md) | API and Database Design |
| [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) | Phased Development Plan |

---

## Security Notes

- Never commit `.env` or any file containing real credentials.
- `DEV_AUTH_BYPASS=true` is for local development only. Always `false` in production.
- All API keys are supplied through environment variables only.
- See `API_DATABASE_DESIGN.md` Section 19 for full security requirements.

---

## License

See [LICENSE](LICENSE) for details.
