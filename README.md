# Travel Itinerary Planner

An AI-powered travel itinerary planning service for Australian destinations. The system uses a structured Agno workflow that combines **CAG** (Cache-Augmented Generation for intent classification) and **RAG** (Retrieval-Augmented Generation for factual enrichment), with database-driven prompt templates and full SSE streaming.

---

## Current Status

**Branch: `feat/fastapi-service`** — `POST /generate` SSE endpoint complete. The full workflow is now reachable over HTTP.

| Branch | Scope | Status |
|--------|-------|--------|
| `feat/project-scaffold` | Dependencies, Docker, directory layout, health endpoint | Done |
| `feat/db-schema` | Alembic migrations, SQLAlchemy models | Done |
| `feat/db-seed` | Category embeddings, prompt templates, source documents | Done |
| `feat/workflow-skeleton` | Agno workflow with 6 stub steps, SSE emitter | Done |
| `feat/intake` | Input validation and normalisation (Step 1) | Done |
| `feat/cag-match` | Embedding-based intent classification (Step 2) | Done |
| `feat/retrieval-decision` | Confidence threshold routing (Step 3) | Done |
| `feat/rag-retrieve` | Agno Knowledge + PgVector top-5 retrieval (Step 4) | Done |
| `feat/generate` | DB-template prompt construction + LLM call (Step 5) | Done |
| `feat/validate-output` | Pydantic validation + retry logic (Step 6) | Done |
| `feat/fastapi-service` | `POST /generate` SSE endpoint | Done |
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

## POST /generate Endpoint

The `POST /generate` endpoint is the public entry point for the workflow. It validates the request, runs the Agno workflow, and streams all step events as Server-Sent Events.

### Request

```http
POST /generate
Content-Type: application/json

{
  "destination": "Sydney",
  "trip_length": 5,
  "budget": "moderate",
  "travel_style": "family"
}
```

All four fields are required. Missing or invalid fields return **422 Unprocessable Entity** — never a 500.

### Response

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream

data: {"session_id": "...", "step": "intake", "status": "completed", ...}

data: {"session_id": "...", "step": "cag_match", "status": "completed", ...}

data: {"session_id": "...", "step": "retrieval_decision", "status": "completed", ...}

data: {"session_id": "...", "step": "generate", "status": "completed", ...}

data: {"session_id": "...", "step": "validate_output", "status": "completed", ...}
```

- Each `data` line is a JSON-serialised SSE event matching DESIGN.md section 9.
- `session_id` is generated per request (`uuid4`) and is identical across all events.
- The `rag_retrieve` event is present only when `confidence_score < 0.78`.
- Events arrive in workflow order: `intake → cag_match → retrieval_decision → (rag_retrieve) → generate → validate_output`.

### How it works

```
POST /generate
  ├── FastAPI validates TravelRequest body  →  422 on bad input
  ├── generate session_id = uuid4()
  ├── _run_workflow(session_id, request)
  │     ├── travel_workflow.run(additional_data={session_id, destination, ...})
  │     │     stdout captured via contextlib.redirect_stdout to collect
  │     │     the retrieval_decision evaluator's side-effect print()
  │     ├── _collect_step_result_events(result.step_results)
  │     │     └── parses intake, cag_match, (rag_retrieve), generate, validate_output
  │     ├── parse retrieval_decision event from captured stdout
  │     └── sort all events by _STEP_ORDER → [0..5]
  └── EventSourceResponse(event_generator())
        └── yields {"data": json.dumps(event)} for each event
```

### Try it

```bash
curl -N -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"destination": "Sydney", "trip_length": 5, "budget": "moderate", "travel_style": "family"}'
```

---

## RAG Knowledge Base

Step 4 (`rag_retrieve`) uses **Agno's built-in `Knowledge` + `PgVector`** rather than raw SQL, keeping retrieval logic within the Agno framework.

### How it works

```
rag_retrieve_executor
  └── retrieval_service.retrieve_documents(query_text, db_url, api_key)
        └── knowledge_base.build_knowledge(db_url, api_key)
              └── Knowledge(vector_db=PgVector(table_name="travel_docs", embedder=GeminiEmbedder))
                    └── knowledge.search(query, max_results=5)  →  List[Document]
```

- **Table**: `travel_docs` in the `ai` schema — created and managed automatically by Agno's `PgVector`. Separate from the `source_documents` Alembic-managed table.
- **Embedder**: `GeminiEmbedder` — a custom Agno-compatible wrapper around `google-genai` using `gemini-embedding-001` (768 dims, `SEMANTIC_SIMILARITY`), matching the model used for CAG and seed embeddings.
- **Search type**: vector (cosine distance).
- **Top-k**: 5 chunks by default.
- **Graceful degradation**: any exception in embedding or search is caught and logged; the step always completes and emits an SSE event, returning an empty `retrieved_context` list on failure.

### Seeding the knowledge base

`scripts/seed.py` inserts itinerary categories, 3 prompt templates (including the correction template for validate_output), and 13 Australian travel documents into the knowledge base using `knowledge.insert()`:

```bash
python scripts/dev.py seed
```

Documents store `destination` and category tags in `meta_data` so they are accessible after retrieval.

---

## Generate Step

Step 5 (`generate`) resolves the active prompt template from the database and calls the Gemini LLM.

### How it works

```
generate_executor
  ├── reads upstream state:
  │     intake       → destination, trip_length, budget, travel_style
  │     cag_match    → matched_category, confidence_score, tone, constraints
  │     rag_retrieve → retrieved_context (empty string if step was skipped)
  ├── selects template key:
  │     confidence_score >= 0.78  →  high_confidence_minimal_context
  │     confidence_score <  0.78  →  low_confidence_with_retrieval
  ├── template_resolver.resolve_template(template_key, db_url)
  │     └── queries prompt_templates WHERE template_key=? AND is_active=true
  ├── _format_template(template_text, variables)
  │     └── regex substitution — safely handles literal { } in the JSON schema example
  └── _call_llm(prompt, api_key, model)  →  raw_llm_output
```

### Template selection

Three prompt templates are seeded in `prompt_templates`:

| `template_key` | Used by | Purpose |
|---|---|---|
| `high_confidence_minimal_context` | `generate` (confidence ≥ 0.78) | Minimal prompt, no RAG context |
| `low_confidence_with_retrieval` | `generate` (confidence < 0.78) | RAG-augmented prompt |
| `validate_output_correction` | `validate_output` (on first failure) | Corrective retry prompt |

All templates are versioned (`version`, `is_active`) and fetched from the database at runtime — never hardcoded. The resolved `prompt_template_version` is written to the SSE event `data` field for traceability.

### SSE output

```json
{
  "session_id": "...",
  "step": "generate",
  "status": "completed",
  "data": {
    "raw_llm_output": "{ ... }",
    "prompt_template_key": "high_confidence_minimal_context",
    "prompt_template_version": 1
  }
}
```

---

## Validate Output Step

Step 6 (`validate_output`) parses `raw_llm_output` from the generate step against a Pydantic schema and retries once on failure.

### How it works

```
validate_output_executor
  ├── _extract_raw_llm_output(step_input)
  │     └── reads raw_llm_output from generate SSE event
  ├── parse_llm_output(raw_text)                        [attempt 1]
  │     ├── strip markdown fences (```json … ```)
  │     ├── json.loads(cleaned_text)
  │     └── ItineraryOutput.model_validate(data)
  │
  ├── [success] → emit SSE with itinerary + degraded_mode=False
  │
  └── [failure] → retry once:
        ├── resolve_template("validate_output_correction", db_url)
        ├── _build_correction_prompt(template, raw_output, errors)
        ├── _call_llm(correction_prompt, ...)
        ├── parse_llm_output(retry_output)              [attempt 2]
        ├── [success] → emit SSE with itinerary + degraded_mode=True
        └── [failure] → emit SSE status="error" + degraded_mode=True
                        (no unhandled exception)
```

### Output schema (`ItineraryOutput`)

```python
class DailyItineraryItem(BaseModel):
    day: int
    morning: str
    afternoon: str
    evening: str
    estimated_cost_aud: float

class ItineraryOutput(BaseModel):
    destination: str
    trip_length_days: int
    budget_level: str
    travel_style: str
    daily_itinerary: List[DailyItineraryItem]
    total_estimated_cost_aud: float
    key_tips: List[str]
```

### SSE output

```json
{
  "session_id": "...",
  "step": "validate_output",
  "status": "completed",
  "data": {
    "itinerary": { "destination": "Sydney", "trip_length_days": 5, "..." : "..." },
    "degraded_mode": false
  }
}
```

On unrecoverable failure: `"status": "error"`, `"degraded_mode": true`, `"error": "Validation failed after retry: ..."`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + sse-starlette |
| Workflow | Agno (`Step`, `Condition`) |
| Knowledge base | Agno `Knowledge` + `PgVector` (`travel_docs` table) |
| Database | PostgreSQL 16 + pgvector |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| LLM | Gemini 2.0 Flash (`google-genai`) |
| Embeddings | `gemini-embedding-001` (Google, 768 dims) |
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

**4. Apply migrations**
```bash
python scripts/dev.py migrate
```

**5. Start the app**
```bash
PYTHONPATH=src uvicorn app.main:app --reload   # macOS / Linux
$env:PYTHONPATH="src"; uvicorn app.main:app --reload  # Windows PowerShell
```

---

## Dev Commands

All commands work on Windows and Unix via the Python task runner:

```bash
python scripts/dev.py up             # start PostgreSQL
python scripts/dev.py down           # stop PostgreSQL
python scripts/dev.py install        # pip install -e ".[dev]"
python scripts/dev.py migrate        # alembic upgrade head
python scripts/dev.py seed           # seed categories, prompt templates, source docs
python scripts/dev.py count-rows     # print row counts + embedding coverage for seeded tables
python scripts/dev.py check-health   # GET /health → 200
python scripts/dev.py test           # pytest
python scripts/dev.py verify         # up → migrate → uvicorn → health + pytest
python scripts/dev.py verify-schema  # up → migrate → db-schema tests (16 checks)
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
| `EMBEDDING_MODEL` | Embedding model — must match seed and cag_match (default: `gemini-embedding-001`) |
| `APP_HOST` | Uvicorn bind host |
| `APP_PORT` | Uvicorn bind port |

---

## Project Layout

```
.
├── src/
│   └── app/
│       ├── main.py          # FastAPI entrypoint — GET /health + POST /generate (SSE)
│       ├── models/
│       │   ├── base.py               # SQLAlchemy DeclarativeBase
│       │   ├── itinerary_category.py # itinerary_categories table + Vector(768)
│       │   ├── prompt_template.py    # prompt_templates table
│       │   ├── source_document.py    # source_documents table + Vector(768)
│       │   └── trace_event.py        # trace_events table
│       └── workflow/
│           ├── sse.py                # SSE event builder (build_sse_event, sse_event_to_json)
│           ├── intake_model.py       # TravelRequest Pydantic model (Step 1 data contract)
│           ├── travel_workflow.py    # Agno Workflow — 6 steps registered in order
│           ├── cag_matcher.py        # CAG logic: embed intent → pgvector search → MatchResult
│           ├── gemini_embedder.py    # Agno-compatible Gemini embedder (wraps google-genai)
│           ├── knowledge_base.py     # Factory: Knowledge + PgVector(travel_docs) + GeminiEmbedder
│           ├── retrieval_service.py  # RAG logic: knowledge.search() → list[RetrievedChunk]
│           ├── template_resolver.py  # DB lookup: resolve_template(key) → (text, version)
│           ├── output_validator.py   # ItineraryOutput Pydantic schema + parse_llm_output()
│           └── steps/
│               ├── intake.py              # Step 1 — validates + normalises input (TravelRequest)
│               ├── cag_match.py           # Step 2 — Gemini embed + cosine match → matched_category
│               ├── retrieval_decision.py  # Step 3 — confidence >= 0.78 → skip RAG, else retrieve
│               ├── rag_retrieve.py        # Step 4 — Agno Knowledge top-5 retrieval → retrieved_context
│               ├── generate.py            # Step 5 — DB prompt template + LLM call → raw_llm_output
│               └── validate_output.py     # Step 6 — Pydantic validation, retry once, structured error
├── tests/
│   ├── conftest.py              # loads .env; redirects Agno logger to stderr
│   ├── test_db_schema.py        # 16 tests covering the db-schema merge checklist
│   ├── test_workflow_skeleton.py # 22 tests covering the workflow-skeleton merge checklist
│   ├── test_intake.py           # 22 tests covering the intake merge checklist
│   ├── test_cag_match.py        # 15 unit + 3 integration tests covering the cag-match checklist
│   ├── test_retrieval_decision.py # 16 tests covering the retrieval-decision merge checklist
│   ├── test_rag_retrieve.py     # 17 tests covering the rag-retrieve merge checklist
│   ├── test_generate.py         # 24 tests covering the generate merge checklist
│   └── test_validate_output.py  # 26 tests covering the validate-output merge checklist
├── alembic/
│   ├── env.py               # loads .env, imports models, runs migrations
│   ├── script.py.mako       # migration file template
│   └── versions/
│       ├── 0001_enable_pgvector_create_itinerary_categories.py
│       ├── 0002_create_prompt_templates.py
│       ├── 0003_create_source_documents.py
│       └── 0004_create_trace_events.py
├── scripts/
│   ├── dev.py               # cross-platform task runner
│   └── seed.py              # seed itinerary_categories, prompt_templates, source_documents
├── docs/
│   ├── DESIGN.md            # single source of truth for system design
│   ├── CLAUDE.md            # AI usage guidelines for this repo
│   └── git-workflow.md      # feature branch order and merge checklist
├── alembic.ini              # Alembic config (DB URL injected from env)
├── docker-compose.yml       # PostgreSQL + pgvector
├── pyproject.toml           # dependencies and project metadata
├── Makefile                 # thin wrappers around scripts/dev.py
└── .env.example             # required environment variables with comments
```

---

## Running Tests

Tests are split into two tiers:

**Unit tests** — no database or API key required, run anywhere:
```bash
python -m pytest tests/ -m "not integration" -v
```

**Integration tests** — require Docker (PostgreSQL) and a real `GEMINI_API_KEY` in `.env`:
```bash
# 1. start db + apply migrations + seed data
python scripts/dev.py up
python scripts/dev.py migrate
python scripts/dev.py seed

# 2. run integration tests only
python -m pytest tests/ -m integration -v

# 3. or run everything together
python -m pytest tests/ -v
```

`tests/conftest.py` loads `.env` automatically so environment variables do not need to be exported manually before running pytest.

---

## Design Docs

- [DESIGN.md](docs/DESIGN.md) — data model, workflow steps, SSE contract, prompt strategy
- [git-workflow.md](docs/git-workflow.md) — branch order, scope, and merge checklist
- [CLAUDE.md](docs/CLAUDE.md) — AI tool usage rules and architecture constraints
