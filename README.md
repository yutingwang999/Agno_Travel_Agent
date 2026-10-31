# Travel Itinerary Planner

An AI-powered travel itinerary planning service for Australian destinations. The system uses a structured Agno workflow that combines **CAG** (Cache-Augmented Generation for intent classification) and **RAG** (Retrieval-Augmented Generation for factual enrichment), with database-driven prompt templates and full SSE streaming.

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
  3. retrieval_decision  — confidence >= 0.85 → skip RAG, else retrieve
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

| Layer            | Technology                                          |
| ---------------- | --------------------------------------------------- |
| API              | FastAPI + sse-starlette                             |
| Workflow         | Agno (`Step`, `Condition`)                          |
| Knowledge base   | Agno `Knowledge` + `PgVector` (`travel_docs` table) |
| Database         | PostgreSQL 16 + pgvector                            |
| ORM / migrations | SQLAlchemy 2 + Alembic                              |
| LLM              | Gemini 2.0 Flash (`google-genai`)                   |
| Embeddings       | `gemini-embedding-001` (Google, 768 dims)           |
| Validation       | Pydantic v2                                         |

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

**5. Seed the database**

```bash
python scripts/dev.py seed
```

**6. Start the app**

```bash
PYTHONPATH=src uvicorn app.main:app --reload   # macOS / Linux
$env:PYTHONPATH="src"; uvicorn app.main:app --reload  # Windows PowerShell
```

---

## Environment Variables

All variables are documented in [.env.example](.env.example).

| Variable            | Purpose                                                                           |
| ------------------- | --------------------------------------------------------------------------------- |
| `POSTGRES_USER`     | PostgreSQL username                                                               |
| `POSTGRES_PASSWORD` | PostgreSQL password                                                               |
| `POSTGRES_DB`       | Database name                                                                     |
| `POSTGRES_PORT`     | Host port to expose (default `5432`)                                              |
| `DATABASE_URL`      | Full SQLAlchemy / Alembic DSN                                                     |
| `TEST_DATABASE_URL` | Test database for integration / destructive tests; name must end with `_test_db`  |
| `EVAL_DATABASE_URL` | Evaluation database; name must end with `_eval_db` (see "How to run the evaluation") |
| `GEMINI_API_KEY`    | Google Gemini API key                                                             |
| `OPENAI_API_KEY`    | Judge model for the evaluation only; the app does not use it                      |
| `LLM_MODEL`         | Gemini model for generation (e.g. `gemini-3.1-flash-lite`)                          |
| `EMBEDDING_MODEL`   | Embedding model — must match seed and cag_match (default: `gemini-embedding-001`) |
| `APP_HOST`          | Uvicorn bind host                                                                 |
| `APP_PORT`          | Uvicorn bind port                                                                 |

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
python scripts/dev.py test              # unit tests only (plain pytest)
python scripts/dev.py test-db-setup     # create + migrate + seed the test database
python scripts/dev.py test-integration  # integration + golden tests on the test database
python scripts/dev.py test-destructive  # migration tests, then re-seed the test database
python scripts/dev.py test-all          # unit → integration → destructive + re-seed
python scripts/dev.py verify            # up → migrate → uvicorn → health + unit tests
python scripts/dev.py verify-schema     # db-schema tests on the test database, then re-seed
python scripts/dev.py eval-db-setup     # create + migrate + seed the evaluation database
```

On macOS/Linux you can also use `make <target>` as a shorthand.

---

## Browser UI

The app serves a single-page frontend at `GET /` from `src/app/static/index.html` — plain HTML + vanilla JS, no build step required.

### Starting the app

```bash
# Windows PowerShell
$env:PYTHONPATH="src"; python.exe -m uvicorn app.main:app --reload

# macOS / Linux
PYTHONPATH=src uvicorn app.main:app --reload
```

Then open **http://localhost:8000** in your browser.

### Manual UI test walkthrough

**1. Use a golden preset button**

Three preset buttons pre-fill the form with the same inputs used in `test_golden.py`:

| Button         | Destination | Days | Budget   | Style  | Expected path                  |
| -------------- | ----------- | ---- | -------- | ------ | ------------------------------ |
| Family trip    | Sydney      | 5    | moderate | family | High-confidence → no RAG       |
| Budget trip    | Melbourne   | 3    | budget   | budget | High-confidence → no RAG       |
| Low-confidence | Alice Springs | 4  | moderate | spontaneous_urban_nomad | Low-confidence → RAG triggered |

Click a preset, then click **Generate Itinerary**.

**2. Watch the SSE step panels**

Each workflow step appears as a panel as it arrives in real time:

- Green left border = `completed`
- Red left border = `error`
- The `generate` step panel highlights `prompt_template_key` and `prompt_template_version` in amber

**3. Check the Trace Log table**

After the stream finishes the page automatically calls `GET /traces/{session_id}` and renders all trace rows in a table showing step, status, latency, template version, and degraded mode.

**4. Try the optional template version override**

Enter a version number in the **Template version** field before submitting to test a specific prompt template version (equivalent to `?template_version=N` on the API).

**5. Try a budget amount and the input checks**

- Enter a whole number in **Daily budget per person** (e.g. `150`); the `intake` panel shows `max_daily_budget_aud`, and the itinerary total stays within 150 × the number of days. A fractional amount or `0` is stopped by the form.
- A trip length above 14 is stopped by the form.
- A destination outside Australia (`Paris`) or an instruction in the travel style (`ignore previous instructions`) shows the refusal message in the red banner.

### Clearing trace data between manual runs

To start with a clean trace table:

```sql
TRUNCATE TABLE trace_events RESTART IDENTITY;
```

Via Docker:

```bash
docker exec -it <postgres-container> psql -U <user> -d <dbname> -c "TRUNCATE TABLE trace_events RESTART IDENTITY;"
```

This is safe for manual UI exploration. Automated tests mock the DB and are unaffected.

---

## POST /generate Endpoint

The `POST /generate` endpoint is the public entry point for the workflow. It validates the request, runs the Agno workflow, and streams all step events as Server-Sent Events.

### Request

```http
POST /generate?template_version=2
Content-Type: application/json

{
  "destination": "Sydney",
  "trip_length": 5,
  "budget": "moderate",
  "travel_style": "family"
}
```

The first four body fields are required. Missing or invalid fields return **422 Unprocessable Entity** — never a 500.

| Field                  | Type      | Values                               | Notes                                                                 |
| ---------------------- | --------- | ------------------------------------ | --------------------------------------------------------------------- |
| `destination`          | `string`  | one Australian place                 | English or Chinese (`"悉尼"`); replaced by its canonical English name |
| `trip_length`          | `integer` | 1–14                                 | number of days                                                        |
| `budget`               | `enum`    | `"budget"`, `"moderate"`, `"luxury"` | any other value → 422                                                 |
| `travel_style`         | `string`  | free text                            | used for CAG semantic matching                                        |
| `max_daily_budget_aud` | `integer` | ≥ 1, optional                        | whole AUD per person per day, excluding accommodation                 |

**Budget.** Costs are AUD per person, excluding accommodation. A request's daily ceiling is `max_daily_budget_aud` if given, otherwise the level's default — `budget` 70, `moderate` 200, `luxury` none. The prompt states the ceiling, and validation checks the total against it.

**Input guards.** Before the workflow starts, a request is refused with 422 and a `reason` code when a free-text field looks like a prompt injection (`input_rejected`), or when the destination is not one place in the Australian place list (`destination_out_of_scope`). The list covers Australian places of at least 1,000 people, states and territories, major tourist destinations, and one Chinese name per major place; it may wrongly refuse a small place, and it refuses vague destinations ("Australia", "the east coast") and two destinations at once. Field errors keep FastAPI's body without a `reason`. Details and the exact bodies: [docs/api.md](docs/api.md) ("Input guards", "Error responses").

**Optional query parameter:**

| Parameter          | Type      | Default | Effect                                                             |
| ------------------ | --------- | ------- | ------------------------------------------------------------------ |
| `template_version` | `integer` | none    | fetch a specific prompt template version instead of the active one |

When `template_version` is omitted the active template (`is_active=true`) is used. Pass an explicit version to reproduce a past run or test a specific template version.

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
- The `rag_retrieve` event is present only when `confidence_score < 0.85`.
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
# Active template (default)
curl -N -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"destination": "Sydney", "trip_length": 5, "budget": "moderate", "travel_style": "family"}'

# Specific template version
curl -N -X POST "http://localhost:8000/generate?template_version=2" \
  -H "Content-Type: application/json" \
  -d '{"destination": "Sydney", "trip_length": 5, "budget": "moderate", "travel_style": "family"}'
```

### GET /traces/{session_id}

Returns all `trace_events` rows for a session as a JSON array ordered by `created_at`.

```http
GET /traces/abc-123-def
```

**200 response:**

```json
[
  {
    "session_id": "abc-123-def",
    "step_name": "intake",
    "status": "completed",
    "latency_ms": 4.2,
    "prompt_template_key": null,
    "prompt_template_version": null,
    "degraded_mode": null,
    "error_type": null,
    "created_at": "..."
  },
  {
    "session_id": "abc-123-def",
    "step_name": "generate",
    "status": "completed",
    "latency_ms": 2341.8,
    "prompt_template_key": "high_confidence_minimal_context",
    "prompt_template_version": 1,
    "degraded_mode": null,
    "error_type": null,
    "created_at": "..."
  }
]
```

**404** when no rows exist for that `session_id`.

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

`scripts/seed.py` inserts itinerary categories, every version of the 3 prompt templates (including the correction template for validate_output; version 2 states that all costs are AUD per person, excluding accommodation, and version 3 of the two generation templates adds the daily budget ceiling), and 13 Australian travel documents into the knowledge base using `knowledge.insert()`:

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
  │     confidence_score >= 0.85  →  high_confidence_minimal_context
  │     confidence_score <  0.85  →  low_confidence_with_retrieval
  ├── template_resolver.resolve_template(template_key, db_url, version=None)
  │     ├── version=None  → WHERE template_key=? AND is_active=true
  │     └── version=N     → WHERE template_key=? AND version=N
  ├── _format_template(template_text, variables)
  │     └── regex substitution — safely handles literal { } in the JSON schema example
  └── _call_llm(prompt, api_key, model)  →  raw_llm_output
```

### Template selection

Three prompt templates are seeded in `prompt_templates`:

| `template_key`                    | Used by                              | Purpose                        |
| --------------------------------- | ------------------------------------ | ------------------------------ |
| `high_confidence_minimal_context` | `generate` (confidence ≥ 0.85)       | Minimal prompt, no RAG context |
| `low_confidence_with_retrieval`   | `generate` (confidence < 0.85)       | RAG-augmented prompt           |
| `validate_output_correction`      | `validate_output` (on first failure) | Corrective retry prompt        |

All templates are versioned (`version`, `is_active`) and fetched from the database at runtime — never hardcoded. The resolved `prompt_template_version` is written to the SSE event `data` field for traceability.

Changing a template: add a new entry to `TEMPLATE_DEFINITIONS` in `scripts/seed.py` (existing versions are never edited), set its number in `ACTIVE_TEMPLATE_VERSIONS`, and run `python scripts/dev.py seed`. Seed makes exactly the declared version of each key active; rolling back is changing the number back and re-running seed. The database allows only one active version per key (migration `0006`), and seed stops before writing if a declared version is not defined.

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

````
validate_output_executor
  ├── _extract_raw_llm_output(step_input)
  │     └── reads raw_llm_output from generate SSE event
  ├── _build_validation_context(step_input)
  │     └── requested trip_length + daily budget ceiling (intake event),
  │         knowledge context = chunk_text of every rag_retrieve chunk
  ├── parse_llm_output(raw_text, context)               [attempt 1]
  │     ├── strip markdown fences (```json … ```)       (fallback; Gemini returns plain JSON)
  │     ├── json.loads(cleaned_text)
  │     ├── ItineraryOutput.model_validate(data)
  │     └── business rules (business_rules.py), every failure reported:
  │           ├── day count: internally consistent and equal to the requested trip_length
  │           ├── cost: daily costs add up to the total (± max(1 AUD, 1%))
  │           ├── budget: total ≤ daily ceiling × days (per person, excl. accommodation)
  │           └── unsupported: opening hours and prices in the text must be in the knowledge context
  │
  ├── [success] → emit SSE with itinerary + degraded_mode=False
  │
  └── [failure] → retry once:
        ├── resolve_template("validate_output_correction", db_url)
        ├── _build_correction_prompt(template, raw_output, errors)
        ├── _call_llm(correction_prompt, ...)
        ├── parse_llm_output(retry_output, context)     [attempt 2]
        ├── [success] → emit SSE with itinerary + degraded_mode=True
        └── [failure] → emit SSE status="error" + degraded_mode=True
                        (no unhandled exception)
````

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
    "itinerary": {
      "destination": "Sydney",
      "trip_length_days": 5,
      "...": "..."
    },
    "degraded_mode": false
  }
}
```

On unrecoverable failure: `"status": "error"`, `"degraded_mode": true`, `"error": "Validation failed after retry: ..."`.

---

## Observability

Every workflow step writes one row to the `trace_events` table after it completes. This gives a full per-request audit trail without coupling the steps to any streaming or logging infrastructure.

### How it works

```
write_trace(db_url, session_id, step_name, status, latency_ms, **step_fields)
  └── creates SQLAlchemy engine → inserts TraceEvent row → commits
      any DB error is caught and logged — never propagates to the caller
```

`trace_logger.write_trace` is imported by each step executor and called on every exit path — success, error, and degraded-mode retry.

### trace_events schema

| Column                    | Type           | Steps                                                      |
| ------------------------- | -------------- | ---------------------------------------------------------- |
| `session_id`              | `String(100)`  | all                                                        |
| `step_name`               | `String(100)`  | all                                                        |
| `status`                  | `String(50)`   | all — `"completed"` or `"error"`                           |
| `latency_ms`              | `Float`        | all — wall-clock duration of the step                      |
| `prompt_template_key`     | `String(100)`  | `generate` only                                            |
| `prompt_template_version` | `Integer`      | `generate` only                                            |
| `degraded_mode`           | `Boolean`      | `validate_output` only — `True` when a retry was attempted |
| `error_type`              | `String(200)`  | `validate_output` only — short description on failure      |
| `created_at`              | `DateTime(tz)` | all — server default                                       |

### Example rows after a full low-confidence run

```
session_id             step_name            status     latency_ms  prompt_template_key              degraded_mode
─────────────────────  ───────────────────  ─────────  ──────────  ───────────────────────────────  ─────────────
abc123…                intake               completed  4.2         null                             null
abc123…                cag_match            completed  312.0       null                             null
abc123…                retrieval_decision   completed  0.1         null                             null
abc123…                rag_retrieve         completed  890.5       null                             null
abc123…                generate             completed  2341.8      low_confidence_with_retrieval    null
abc123…                validate_output      completed  12.3        null                             false
```

### Querying traces

```sql
-- All steps for a session, in order
SELECT step_name, status, latency_ms, degraded_mode
FROM trace_events
WHERE session_id = 'abc123...'
ORDER BY created_at;

-- Degraded validate_output runs in the last hour
SELECT session_id, error_type, latency_ms, created_at
FROM trace_events
WHERE step_name = 'validate_output'
  AND degraded_mode = true
  AND created_at > now() - interval '1 hour';
```

---

## Running Tests

Tests never touch the development database. Integration and migration tests run against a separate test database, `travel_agent_test_db`, in the same Postgres container: `tests/conftest.py` replaces `DATABASE_URL` with `TEST_DATABASE_URL` before any application code is imported.

Tests are split into three tiers:

| Tier | Marker | Needs | Command |
| --- | --- | --- | --- |
| Unit | none | nothing (DB and LLM are mocked) | `python -m pytest` or `python scripts/dev.py test` |
| Integration | `integration` | seeded test database + `GEMINI_API_KEY`; costs API calls | `python -m pytest -m integration` or `python scripts/dev.py test-integration` |
| Destructive | `destructive` | test database; **wipes it** (`alembic downgrade base`) | `python scripts/dev.py test-destructive` |

Plain `pytest` runs unit tests only (`addopts` in `pyproject.toml`); a `-m` on the command line overrides that. Run a single test with `python -m pytest tests/test_generate.py::test_name -v`.

**One-time setup for integration and destructive tests**

1. Copy `TEST_DATABASE_URL` from `.env.example` into `.env` (the database name must end with `_test_db`).
2. Start Postgres and prepare the test database:

```bash
python scripts/dev.py up
python scripts/dev.py test-db-setup   # create (if missing) -> migrate -> seed; safe to re-run
```

Seeding is idempotent: rows that already exist are skipped before any embedding call, so re-running `test-db-setup` costs nothing.

**When to run what**

- Day to day: `python scripts/dev.py test`
- After changing workflow behaviour: `python scripts/dev.py test-integration` (includes the golden tests and the end-to-end `POST /generate` test)
- After changing a migration: `python scripts/dev.py test-destructive` — it runs `alembic downgrade base` / `upgrade head` on the test database, then re-runs `test-db-setup` automatically to restore the seed data, whether the tests passed or failed
- Before merging: `python scripts/dev.py test-all` (unit → integration → destructive + restore)

Don't use `pytest -m ""` to run everything at once: files run in alphabetical order, so the migration tests would empty the test database before the golden tests.

If `TEST_DATABASE_URL` is not set, integration and destructive tests are skipped with a reason, and unit tests point `DATABASE_URL` at an unreachable placeholder rather than the development database. The migration tests also refuse to run against any database whose name does not end with `_test_db`.

`tests/conftest.py` loads `.env` automatically, so environment variables do not need to be exported manually before running pytest.

---

## How to run the evaluation

Tests check that the code works; the evaluation measures how good the itineraries are — retrieval recall, behaviour correctness, budget and day constraints, faithfulness to the knowledge context — on a fixed dataset of 73 requests (`eval/dataset.jsonl`). Full instructions are in [docs/evaluation.md](docs/evaluation.md); measured results are in [docs/experiments.md](docs/experiments.md).

**Its own database.** The evaluation runs against `travel_agent_eval_db` (`EVAL_DATABASE_URL`, name must end with `_eval_db`), never the test database: tests reseed and wipe `travel_agent_test_db`, and its small fixture corpus is not the corpus being measured. Evaluation numbers come only from the evaluation database; each knowledge-base version gets its own table there (`travel_docs_v1`), so earlier results can be re-run.

**Keys.** Generation and embeddings use `GEMINI_API_KEY`. Faithfulness and "attractions in the destination" are decided by a judge model from another provider, which needs `OPENAI_API_KEY`. A full run costs about $0.22 (about two thirds of it the judge) and takes about 12 minutes; the 10-entry smoke subset about $0.03 and 2 minutes.

```bash
python scripts/dev.py eval-db-setup                               # once: create + migrate + seed the evaluation database
python scripts/eval_run.py --config v010-baseline                 # full run -> eval/runs/<run id>/
python scripts/eval_run.py --config v010-baseline --subset smoke  # 10 entries
python scripts/eval_compare.py <run id> <run id>                  # comparison table
python scripts/eval_gate.py                                       # smoke run against eval/thresholds.yaml; non-zero exit on failure
```

Commit before a run you want to cite: a run on uncommitted code is marked `git_dirty` and is for reference only. Each run's `summary.json` is committed; per-entry results are kept in a private repository (see [docs/evaluation.md](docs/evaluation.md), "What is published").

---

## Project Layout

```
.
├── src/
│   └── app/
│       ├── main.py          # FastAPI entrypoint — GET /health, POST /generate, GET /traces/{id}
│       ├── static/
│       │   └── index.html           # Single-page browser UI (plain HTML + vanilla JS)
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
│           ├── trace_logger.py       # write_trace() — inserts one TraceEvent row per step
│           ├── cag_matcher.py        # CAG logic: embed intent → in-memory cosine match → MatchResult
│           ├── gemini_embedder.py    # Agno-compatible Gemini embedder (wraps google-genai)
│           ├── knowledge_base.py     # Factory: Knowledge + PgVector(travel_docs) + GeminiEmbedder
│           ├── retrieval_service.py  # RAG logic: knowledge.search() → list[RetrievedChunk]
│           ├── template_resolver.py  # DB lookup: resolve_template(key) → (text, version)
│           ├── template_versions.py  # seed helper: insert versions, activate the declared one per key
│           ├── output_validator.py   # ItineraryOutput Pydantic schema + parse_llm_output()
│           └── steps/
│               ├── intake.py              # Step 1 — validates + normalises input (TravelRequest)
│               ├── cag_match.py           # Step 2 — Gemini embed + cosine match → matched_category
│               ├── retrieval_decision.py  # Step 3 — confidence >= 0.85 → skip RAG, else retrieve
│               ├── rag_retrieve.py        # Step 4 — Agno Knowledge top-5 retrieval → retrieved_context
│               ├── generate.py            # Step 5 — DB prompt template + LLM call → raw_llm_output
│               └── validate_output.py     # Step 6 — Pydantic validation, retry once, structured error
├── tests/
│   ├── conftest.py              # loads .env; redirects Agno logger to stderr
│   ├── test_db_schema.py        # db-schema merge checklist (migrations, models, live DB)
│   ├── test_workflow_skeleton.py # workflow-skeleton checklist (SSE structure, 6-step run)
│   ├── test_intake.py           # intake checklist + BudgetLevel enum tests
│   ├── test_cag_match.py        # cag-match checklist (unit + integration)
│   ├── test_retrieval_decision.py # retrieval-decision checklist (threshold logic, SSE)
│   ├── test_rag_retrieve.py     # rag-retrieve checklist (top-k, graceful degradation)
│   ├── test_generate.py         # generate checklist + template version override tests
│   ├── test_validate_output.py  # validate-output checklist + content guardrail tests
│   ├── test_observability.py    # observability checklist (unit + integration)
│   ├── test_fastapi_service.py  # fastapi-service checklist (HTTP layer, 422s, SSE shape)
│   ├── test_golden.py           # 3 golden tests + 1 end-to-end POST /generate test
│   └── test_ui_api.py           # unit tests for GET /traces/{session_id} (DB mocked)
├── alembic/
│   ├── env.py               # loads .env, imports models, runs migrations
│   ├── script.py.mako       # migration file template
│   └── versions/
│       ├── 0001_enable_pgvector_create_itinerary_categories.py
│       ├── 0002_create_prompt_templates.py
│       ├── 0003_create_source_documents.py
│       ├── 0004_create_trace_events.py
│       ├── 0005_add_token_usage_to_trace_events.py
│       └── 0006_single_active_prompt_template.py
├── scripts/
│   ├── dev.py               # cross-platform task runner
│   └── seed.py              # seed itinerary_categories, prompt_templates, source_documents
├── docs/
│   ├── DESIGN.md            # original v0.1.0 design (OpenSpec specs/changes take precedence)
│   ├── CLAUDE.md            # AI usage guidelines for this repo
│   └── git-workflow.md      # feature branch order and merge checklist
├── alembic.ini              # Alembic config (DB URL injected from env)
├── docker-compose.yml       # PostgreSQL + pgvector
├── pyproject.toml           # dependencies and project metadata
├── Makefile                 # thin wrappers around scripts/dev.py
└── .env.example             # required environment variables with comments
```

---

## Current Status

**Branch: `feat/ui`** — browser UI with SSE step panels, trace viewer, and golden preset buttons. Also adds `GET /traces/{session_id}` endpoint.

| Branch                    | Scope                                                       | Status |
| ------------------------- | ----------------------------------------------------------- | ------ |
| `feat/project-scaffold`   | Dependencies, Docker, directory layout, health endpoint     | Done   |
| `feat/db-schema`          | Alembic migrations, SQLAlchemy models                       | Done   |
| `feat/db-seed`            | Category embeddings, prompt templates, source documents     | Done   |
| `feat/workflow-skeleton`  | Agno workflow with 6 stub steps, SSE emitter                | Done   |
| `feat/intake`             | Input validation and normalisation (Step 1)                 | Done   |
| `feat/cag-match`          | Embedding-based intent classification (Step 2)              | Done   |
| `feat/retrieval-decision` | Confidence threshold routing (Step 3)                       | Done   |
| `feat/rag-retrieve`       | Agno Knowledge + PgVector top-5 retrieval (Step 4)          | Done   |
| `feat/generate`           | DB-template prompt construction + LLM call (Step 5)         | Done   |
| `feat/validate-output`    | Pydantic validation + retry logic (Step 6)                  | Done   |
| `feat/fastapi-service`    | `POST /generate` SSE endpoint                               | Done   |
| `feat/observability`      | `trace_events` writes across all steps                      | Done   |
| `feat/testing`            | Unit, integration, end-to-end, and golden tests             | Done   |
| `feat/ui`                 | Browser UI, `GET /traces/{session_id}`, static file serving | Done   |

---

## feat/testing — Branch Changes

This branch completes the full test suite and adds three functional improvements to the workflow.

### Test coverage added

| File                      | Type        | What it covers                                                                  |
| ------------------------- | ----------- | ------------------------------------------------------------------------------- |
| `test_golden.py`          | integration | 3 golden tests (family, budget, low-confidence) + 1 end-to-end `POST /generate` |
| `test_fastapi_service.py` | unit        | `template_version` query param forwarded correctly                              |
| `test_generate.py`        | unit        | `resolve_template` version override, `None` default                             |
| `test_validate_output.py` | unit        | content guardrail pass and fail cases                                           |

**Golden tests** assert structure and branch correctness — not exact LLM output strings:

1. **Family trip** — high-confidence path, no `rag_retrieve` event, structured itinerary returned
2. **Budget trip** — same branch, different destination and style
3. **Low-confidence** — `rag_retrieve` event present, `retrieved_context` non-empty, itinerary returned

**End-to-end test** makes a real HTTP call to `POST /generate` via `TestClient` (no mocking of `_run_workflow`) and asserts all 6 step names appear in the SSE stream with correct structure.

### Functional changes

**`budget` field changed to enum** (`BudgetLevel`):  
Values `"budget"`, `"moderate"`, `"luxury"` are now enforced at the Pydantic layer. Any other string returns 422. `travel_style` remains free text so the CAG step can perform semantic matching on it.

**Prompt template version override** (`?template_version=N`):  
`POST /generate` accepts an optional `template_version` query parameter. When set, `resolve_template` fetches that specific version instead of the active one — enabling reproducibility and A/B testing without changing the database. The version is propagated through `additional_data` to `generate_executor`.

**Content-level output guardrail**:  
`parse_llm_output` now checks that `len(daily_itinerary) == trip_length_days` after Pydantic schema validation. A mismatch triggers the existing retry mechanism in `validate_output_executor` — no extra code path needed. (`harden-workflow-guardrails` extends this into a list of business rules; see "How it works" under validate_output.)

**Seed script robustness fix**:  
`scripts/seed.py` detects when `travel_docs` exists but is missing the `embedding` column (caused by a partial or legacy seed run) and drops + recreates the table before inserting documents.

---

## feat/ui — Branch Changes

This branch adds a browser UI and a traces read endpoint on top of the completed API.

### New files

| File                        | Purpose                                                             |
| --------------------------- | ------------------------------------------------------------------- |
| `src/app/static/index.html` | Single-page UI — form, SSE step panels, trace table, preset buttons |
| `tests/test_ui_api.py`      | 13 unit tests for `GET /traces/{session_id}` (DB mocked)            |

### Changes to existing files

**`src/app/main.py`**

- Added `GET /traces/{session_id}` — queries `trace_events` for all rows matching `session_id`, returns JSON array ordered by `created_at`, 404 when none found
- Added `StaticFiles` mount at `/` serving `src/app/static/` (mounted after all API routes so API routes take precedence)

### UI features

- **Form** — destination, trip_length (1–14), budget (enum select), travel_style, optional daily budget per person, optional template_version; error banner shows field validation messages and guard refusals
- **3 golden preset buttons** — pre-fill the form with the same inputs as `test_golden.py`
- **SSE step panels** — render in real time as each workflow step completes; `generate` panel highlights template key and version
- **Trace table** — auto-fetched from `GET /traces/{session_id}` after stream completes; shows step, status, latency, template version, degraded mode

---

## Data sources and licences

| Data | Used for | Source and licence | Details |
| --- | --- | --- | --- |
| Australian place list (`data/places/australia.tsv`) | The destination guard: which destinations are accepted, and their canonical English names | Place names from [GeoNames](https://www.geonames.org/) (`cities1000`), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), plus hand-kept lists of states, tourist destinations and Chinese names written for this project. Contains data from GeoNames (https://www.geonames.org/), licensed under CC BY 4.0. Modified: only Australian places are used, names are lowercased, and the list is combined with hand-kept lists written for this project. | [data/places/SOURCES.md](data/places/SOURCES.md) |
| Knowledge base, corpus v1 (13 documents in `scripts/seed.py`) | RAG context for generation | Short handwritten summaries written for v0.1.0. To be replaced in `rebuild-rag` by openly licensed sources (mainly Wikivoyage, CC BY-SA), each listed here with its licence | `scripts/seed.py` (`SOURCE_DOCUMENTS`) |

---

## Design Docs

- [DESIGN.md](docs/DESIGN.md) — data model, workflow steps, SSE contract, prompt strategy
- [api.md](docs/api.md) — full API reference: request/response formats, SSE event shapes per step, and how each failure inside the workflow is reported ("Failure behaviour")
- [git-workflow.md](docs/git-workflow.md) — branch order, scope, and merge checklist
- [CLAUDE.md](docs/CLAUDE.md) — AI tool usage rules and architecture constraints
