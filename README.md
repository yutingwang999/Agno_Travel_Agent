# Travel Itinerary Planner

An AI-powered travel itinerary planning service for Australian destinations. The system uses a structured Agno workflow that combines **CAG** (Cache-Augmented Generation for intent classification) and **RAG** (Retrieval-Augmented Generation for factual enrichment), with database-driven prompt templates and full SSE streaming.

---

## Current Status

**Branch: `feat/project-scaffold`** — environment and entrypoint only.

| Branch | Scope | Status |
|--------|-------|--------|
| `feat/project-scaffold` | Dependencies, Docker, directory layout, health endpoint | In progress |
| `feat/db-schema` | Alembic migrations, SQLAlchemy models | Pending |
| `feat/db-seed` | Category embeddings, prompt templates, source documents | Pending |
| `feat/workflow-skeleton` | Agno workflow with 6 stub steps, SSE emitter | Pending |
| `feat/intake` | Input validation and normalisation (Step 1) | Pending |
| `feat/cag-match` | Embedding-based intent classification (Step 2) | Pending |
| `feat/retrieval-decision` | Confidence threshold routing (Step 3) | Pending |
| `feat/rag-retrieve` | pgvector similarity search (Step 4) | Pending |
| `feat/generate` | DB-template prompt construction + LLM call (Step 5) | Pending |
| `feat/validate-output` | Pydantic validation + retry logic (Step 6) | Pending |
| `feat/fastapi-service` | `POST /generate` SSE endpoint | Pending |
| `feat/observability` | `trace_events` writes across all steps | Pending |
| `feat/testing` | Unit, integration, end-to-end, and golden tests | Pending |

---

## Architecture

```
POST /generate
      │
      ▼
FastAPI Service
      │  creates session_id, validates request
      ▼
Agno Workflow
  1. intake              — validate + normalise input fields
  2. cag_match           — embed intent, cosine match against itinerary_categories
  3. retrieval_decision  — confidence >= 0.78 → skip RAG, else retrieve
  4. rag_retrieve        — pgvector top-5 similarity search on source_documents
  5. generate            — resolve DB prompt template, call LLM
  6. validate_output     — Pydantic schema check, retry once on failure
      │
      ▼
SSE stream (one structured event per step)
```

Each SSE event has the form:
```json
{
  "session_id": "...",
  "step": "cag_match",
  "status": "completed",
  "timestamp": "...",
  "data": {},
  "error": null
}
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + sse-starlette |
| Workflow | Agno (`Step`, `Condition`) |
| Database | PostgreSQL 16 + pgvector |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| LLM | Gemini 2.0 Flash (`google-generativeai`) |
| Embeddings | `text-embedding-004` (Google) |
| Validation | Pydantic v2 |

---

## Prerequisites

- Python 3.11+
- Docker Desktop

---

## Setup

**1. Clone and copy env file**
```bash
git clone <repo-url>
cd Agno_Travel_Agent
cp .env.example .env
# fill in GEMINI_API_KEY in .env
```

**2. Install dependencies**
```bash
python scripts/dev.py install
```

**3. Start PostgreSQL**
```bash
python scripts/dev.py up
```

**4. Start the app**
```bash
PYTHONPATH=src uvicorn app.main:app --reload   # macOS / Linux
$env:PYTHONPATH="src"; uvicorn app.main:app --reload  # Windows PowerShell
```

---

## Dev Commands

All commands work on Windows and Unix via the Python task runner:

```bash
python scripts/dev.py up           # start PostgreSQL
python scripts/dev.py down         # stop PostgreSQL
python scripts/dev.py install      # pip install -e ".[dev]"
python scripts/dev.py check-health # GET /health → 200
python scripts/dev.py test         # pytest
python scripts/dev.py verify       # run the full scaffold checklist
```

On macOS/Linux you can also use `make <target>` as a shorthand.

---

## Environment Variables

All variables are documented in [.env.example](.env.example).

| Variable | Purpose |
|----------|---------|
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | Database name |
| `POSTGRES_PORT` | Host port to expose (default `5432`) |
| `DATABASE_URL` | Full SQLAlchemy / Alembic DSN |
| `GEMINI_API_KEY` | Google Gemini API key |
| `LLM_MODEL` | Gemini model for generation (e.g. `gemini-2.0-flash`) |
| `EMBEDDING_MODEL` | Embedding model — must match seed and cag_match (e.g. `text-embedding-004`) |
| `APP_HOST` | Uvicorn bind host |
| `APP_PORT` | Uvicorn bind port |

---

## Project Layout

```
.
├── src/
│   └── app/
│       └── main.py          # FastAPI entrypoint (health check only, for now)
├── tests/                   # pytest test suite
├── alembic/                 # migrations (added in feat/db-schema)
├── scripts/
│   └── dev.py               # cross-platform task runner
├── docs/
│   ├── DESIGN.md            # single source of truth for system design
│   ├── CLAUDE.md            # AI usage guidelines for this repo
│   └── git-workflow.md      # feature branch order and merge checklist
├── docker-compose.yml       # PostgreSQL + pgvector
├── pyproject.toml           # dependencies and project metadata
├── Makefile                 # thin wrappers around scripts/dev.py
└── .env.example             # required environment variables with comments
```

---

## Design Docs

- [DESIGN.md](docs/DESIGN.md) — data model, workflow steps, SSE contract, prompt strategy
- [git-workflow.md](docs/git-workflow.md) — branch order, scope, and merge checklist
- [CLAUDE.md](docs/CLAUDE.md) — AI tool usage rules and architecture constraints
