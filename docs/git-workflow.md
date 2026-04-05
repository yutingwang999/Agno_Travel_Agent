# Git Workflow

## Purpose

This document defines the feature branch strategy for this project. Its goals:

- keep `main` stable and always runnable
- map each major unit of work to its own branch, making history easy to review
- support incremental implementation that aligns with DESIGN.md
- ensure the `main` branch can be demonstrated or handed off at any point

---

## 1. Definition of "Main Must Stay Runnable"

A commit is only merged to `main` if all of the following are true:

1. `docker compose up` starts PostgreSQL without error
2. `alembic upgrade head` completes without error (all migrations apply cleanly)
3. `uvicorn app.main:app --reload` starts without import errors or missing config
4. `pytest` exits 0 — every test that currently exists must pass
5. POST `/generate` returns a valid response (200 with SSE stream, or a stub 200) — no unhandled 500s
6. No unresolved imports anywhere in `src/`
7. Every required environment variable is documented in `.env.example`
8. Unimplemented workflow steps may be stubs, but stubs must be importable and callable without error

"Runnable" does not mean "feature-complete". It means the app starts, existing tests pass, and
no committed code is broken. Stubs and placeholder responses are acceptable; broken imports and
crashing startups are not.

---

## 2. Feature Branches

Branches are listed in the order they must be implemented. Each branch merges to `main` before
the next one begins.

---

### Branch 1 — `feat/project-scaffold`

**Scope**

- `pyproject.toml` with all dependencies pinned
- Project directory layout: `src/`, `tests/`, `alembic/`
- `docker-compose.yml` for PostgreSQL with pgvector
- `.env.example` listing every required variable with a comment
- Minimal `src/app/main.py` that starts uvicorn without error (health check endpoint only)

**Why first**
Nothing else can be built or tested without a runnable local environment. All subsequent branches
assume Docker + Python environment is working.

---

### Branch 2 — `feat/db-schema`

**Scope**

- Alembic initialisation
- 4 migration files: `itinerary_categories`, `prompt_templates`, `source_documents`, `trace_events`
- SQLAlchemy models for all 4 tables matching the schema in DESIGN.md section 5
- pgvector extension enabled in migration

**Why second**
The database schema is the foundation all workflow steps read from and write to. No step can be
implemented correctly until the tables and column contracts are fixed.

---

### Branch 3 — `feat/db-seed`

**Scope**

- `scripts/seed.py` (idempotent — safe to run multiple times)
- At least 2 `itinerary_categories` rows with pre-computed embedding vectors
- 2 `prompt_templates` rows: `high_confidence_minimal_context` and `low_confidence_with_retrieval`,
  each with `is_active=true` and version `1`
- At least 10 `source_documents` chunks covering Australian destinations, each with embedding vectors

**Why third**
The `cag_match` step queries `itinerary_categories` and the `rag_retrieve` step queries
`source_documents`. Both are blocked until seed data exists. The `generate` step is blocked until
prompt templates exist.

---

### Branch 4 — `feat/workflow-skeleton`

**Scope**

- Agno `Workflow` class with all 6 steps registered in order
- Each step is a stub: accepts workflow state, emits an SSE event, returns state unchanged
- SSE event emitter utility that produces the structured event format from DESIGN.md section 9
- `session_id` propagated through all steps from workflow entry
- No business logic — stubs only

**Why fourth**
Fixing the step interface contract before any step is implemented prevents rework. Each subsequent
step branch fills in one stub without changing the surrounding structure. The skeleton also proves
that the full workflow path can be traversed end-to-end before any real logic exists.

---

### Branch 5 — `feat/intake`

**Scope**

- Step 1 implementation: Pydantic input model (`destination`, `trip_length`, `budget`, `travel_style`)
- Field normalisation (e.g. lowercase destination)
- Returns 422 on invalid or missing required fields — not 500
- Output written to workflow state for downstream steps

**Why fifth**
Step 1 defines the output schema that all downstream steps read. Its Pydantic model is the data
contract for the entire workflow. Nothing else should be implemented until this contract is stable.

---

### Branch 6 — `feat/cag-match`

**Scope**

- Step 2 implementation: embed the user's free-text intent using the same embedding model used in seed
- Cosine similarity search against `itinerary_categories.embedding_vector` using pgvector
- Write `matched_category` and `confidence_score` to workflow state
- Fallback to a default category when no match exceeds a minimum acceptable similarity

**Why sixth**
The `retrieval_decision` step (branch 7) branches on `confidence_score`. That step cannot be
implemented until `cag_match` produces the score it reads.

---

### Branch 7 — `feat/retrieval-decision`

**Scope**

- Step 3 implementation: Agno `Condition` node
- Threshold: `confidence_score >= 0.78` → skip `rag_retrieve`, proceed directly to `generate`
- Threshold: `confidence_score < 0.78` → execute `rag_retrieve` before `generate`
- Branch decision written to SSE event `data` field

**Why seventh**
This is the routing step that determines which of two downstream paths executes. Both paths
(`rag_retrieve` and `generate`) depend on this condition being in place before they can be
tested against realistic workflow execution.

---

### Branch 8 — `feat/rag-retrieve`

**Scope**

- Step 4 implementation: pgvector similarity search on `source_documents.embedding_vector`
- Retrieve top-5 most relevant chunks (or fewer if fewer exist)
- Append `retrieved_context` list to workflow state
- Graceful degradation: if pgvector query fails, log the error and continue with empty context
  (do not crash the workflow)

**Why eighth**
This is the conditional path activated by `retrieval_decision`. It can only be meaningfully
implemented and tested once routing is in place (branch 7) and seed documents exist (branch 3).

---

### Branch 9 — `feat/generate`

**Scope**

- Step 5 implementation: resolve the active versioned prompt template from `prompt_templates`
  by `template_key` and `is_active=true`
- Inject template variables: `destination`, `trip_length`, `budget`, `matched_category`, `tone`,
  `constraints`, and `retrieved_context` (empty string if RAG was skipped)
- Call the LLM with the fully resolved prompt
- Write `raw_llm_output` and `prompt_template_version` to workflow state

**Why ninth**
This step depends on all upstream state: the normalised input (step 1), the matched category and
confidence (step 2), the routing decision (step 3), and optionally the retrieved context (step 4).
All of those must be in place before `generate` can be implemented correctly.

---

### Branch 10 — `feat/validate-output`

**Scope**

- Step 6 implementation: parse `raw_llm_output` against a Pydantic output schema
- On validation failure: retry exactly once using a corrective prompt
- On second failure: return a structured error response (not a 500); set `degraded_mode=true`
  in workflow state
- Valid output passed through unchanged

**Why tenth**
This step completes the workflow. It can only be implemented once `generate` produces real LLM
output to validate. After this branch merges, the workflow is end-to-end functional.

---

### Branch 11 — `feat/fastapi-service`

**Scope**

- `POST /generate` endpoint: validates request body, creates `session_id`, executes Agno workflow
- Response: `Content-Type: text/event-stream` via `sse-starlette`
- Each SSE event matches the structure defined in DESIGN.md section 9
- `session_id` generated per request and included in the first SSE event
- Intake validation errors returned as 422

**Why eleventh**
The API layer wraps a complete workflow. Implementing it before the workflow is complete would
mean the endpoint either crashes or returns meaningless stubs. Keeping it separate also allows
the workflow to be tested directly (without HTTP) in earlier branches.

---

### Branch 12 — `feat/observability`

**Scope**

- `trace_events` DB writes added to all 6 steps
- Every write includes: `session_id`, `step_name`, `status`, `latency_ms`
- `generate` step additionally writes: `prompt_template_key`, `prompt_template_version`
- `validate_output` step additionally writes: `degraded_mode`, `error_type` (when applicable)
- No changes to step business logic — instrumentation only

**Why twelfth**
Observability is added after steps are functionally correct. Mixing instrumentation with initial
step logic makes it harder to isolate bugs — a DB write failure would mask a logic error.
Adding it as a dedicated branch also makes the diff reviewable on its own terms.

---

### Branch 13 — `feat/testing`

**Scope**

- `pytest` configuration (`pyproject.toml` or `pytest.ini`), test database fixture
- Unit tests: template resolver, 0.78 threshold logic, output validator helpers
- Integration tests: DB migrations apply correctly, prompt lookup by key + active version,
  `trace_events` row written after workflow run
- End-to-end test: `POST /generate` → SSE stream contains all 6 step events
- 3 golden tests (validate structure and branch correctness, not exact string content):
  1. Family trip request → high-confidence path, no RAG, structured itinerary returned
  2. Budget trip request → high-confidence path, no RAG, structured itinerary returned
  3. Low-confidence request → RAG path taken, `rag_retrieve` SSE event present in stream

**Why last**
Golden and end-to-end tests require the full pipeline. Unit and integration tests are simpler,
but consolidating all test work into one branch keeps the testing scope reviewable together and
avoids premature test investment against unstable interfaces.

---

## 3. Merge Checklist

### Common checklist (every branch)

- [ ] Branch rebased on latest `main` before opening PR
- [ ] `docker compose up` starts without error
- [ ] `alembic upgrade head` completes without error
- [ ] `uvicorn app.main:app --reload` starts without import errors
- [ ] `pytest` exits 0
- [ ] No hardcoded prompts (all prompt text must come from `prompt_templates` table)
- [ ] All new function and variable names are descriptive (no single-letter or vague names)
- [ ] No changes contradict DESIGN.md
- [ ] PR description includes: files modified, assumptions made, any deviations from DESIGN.md

---

### `feat/project-scaffold`

- [ ] `.env.example` lists every required variable with a one-line comment explaining its purpose
- [ ] `docker compose up` starts PostgreSQL and pgvector on the port documented in `.env.example`
- [ ] `uvicorn app.main:app` starts and returns 200 on the health check route

---

### `feat/db-schema`

- [ ] `alembic upgrade head` creates all 4 tables with correct column names and types
- [ ] `alembic downgrade base` rolls back all migrations cleanly (no leftover tables)
- [ ] `CREATE EXTENSION IF NOT EXISTS vector` present in the first migration
- [ ] SQLAlchemy models match the column definitions in DESIGN.md section 5 exactly

---

### `feat/db-seed`

- [ ] `python scripts/seed.py` run twice produces no duplicate rows (idempotent)
- [ ] At least 2 rows in `itinerary_categories`, each with a non-null `embedding_vector`
- [ ] `high_confidence_minimal_context` and `low_confidence_with_retrieval` templates present,
      both with `is_active=true` and `version=1`
- [ ] At least 10 rows in `source_documents`, each with a non-null `embedding_vector`

---

### `feat/workflow-skeleton`

- [ ] All 6 steps are importable from `src/` without error
- [ ] Running the workflow stub-to-stub produces one SSE event per step (6 total)
- [ ] Every SSE event contains `session_id`, `step`, `status`, and `timestamp`

---

### `feat/intake`

- [ ] Submitting a request with a missing required field returns 422, not 500
- [ ] Normalised fields (e.g. lowercased `destination`) are present in workflow state after step 1
- [ ] Pydantic model covers all 4 fields from DESIGN.md: `destination`, `trip_length`, `budget`,
      `travel_style`

---

### `feat/cag-match`

- [ ] `matched_category` and `confidence_score` present in workflow state after step 2
- [ ] A request that matches no category clearly still completes step 2 with a fallback category
      (no unhandled exception)
- [ ] Embedding model used in `cag_match` is the same model used to generate seed embeddings

---

### `feat/retrieval-decision`

- [ ] A request with `confidence_score >= 0.78` does not execute `rag_retrieve` (verify via SSE
      events — no `rag_retrieve` event in stream)
- [ ] A request with `confidence_score < 0.78` does execute `rag_retrieve` (event present)
- [ ] SSE event for `retrieval_decision` includes the routing decision in its `data` field

---

### `feat/rag-retrieve`

- [ ] Workflow state contains a `retrieved_context` list with up to 5 items after step 4
- [ ] If pgvector query raises an exception, workflow continues with empty `retrieved_context`
      and does not crash
- [ ] SSE event for `rag_retrieve` is emitted regardless of whether results were found

---

### `feat/generate`

- [ ] Prompt template is fetched from `prompt_templates` by `template_key` and `is_active=true`
      (never hardcoded)
- [ ] `prompt_template_version` written to workflow state after step 5
- [ ] `raw_llm_output` present in workflow state after step 5

---

### `feat/validate-output`

- [ ] Valid LLM output passes step 6 without modification
- [ ] Simulated invalid output (wrong schema) triggers exactly one retry, not two or zero
- [ ] After two failures, response is a structured error object — no unhandled 500
- [ ] `degraded_mode=true` present in workflow state whenever a retry was attempted

---

### `feat/fastapi-service`

- [ ] `POST /generate` returns `Content-Type: text/event-stream`
- [ ] SSE event structure matches DESIGN.md section 9 (`session_id`, `step`, `status`,
      `timestamp`, `data`, `error`)
- [ ] `session_id` is unique per request and appears in the first SSE event
- [ ] Invalid request body returns 422

---

### `feat/observability`

- [ ] After a full workflow run, `trace_events` contains exactly 6 rows for that `session_id`
- [ ] Every row has non-null `session_id`, `step_name`, `status`, `latency_ms`
- [ ] The row for `generate` has non-null `prompt_template_key` and `prompt_template_version`
- [ ] The row for `validate_output` has `degraded_mode` and `error_type` set when a retry occurred

---

### `feat/testing`

- [ ] `pytest` exits 0 against a seeded test database
- [ ] Golden test 1 (family trip): workflow takes the high-confidence path, response contains a
      structured itinerary, no `rag_retrieve` SSE event
- [ ] Golden test 2 (budget trip): same as above with budget-appropriate output
- [ ] Golden test 3 (low-confidence request): `rag_retrieve` SSE event present, response contains
      structured itinerary with retrieved context injected
- [ ] Golden tests assert structure (required fields present) and branch correctness
      (correct SSE events emitted) — they do NOT assert exact LLM output strings

---

## 4. Why This Order

The sequence follows a strict dependency chain: each layer can only be built on top of a stable
layer below it.

**Scaffold first** — no code runs without a working environment, Docker, and a startup entrypoint.

**DB schema before seed** — you cannot insert rows into tables that do not exist. Schema defines
the contract; seed fills it.

**Seed before workflow steps** — `cag_match` queries `itinerary_categories` and `rag_retrieve`
queries `source_documents`. Both would return empty or error without seed data. `generate` needs
prompt templates to exist.

**Workflow skeleton before individual steps** — fixing the step function signatures, the SSE event
format, and the `session_id` propagation pattern before any step has real logic prevents breaking
changes mid-implementation. The skeleton acts as a scaffold that each step branch fills in without
touching the surrounding structure.

**Steps in workflow order (1 → 6)** — each step reads from the state written by the step before
it. `retrieval_decision` reads `confidence_score` from `cag_match`. `generate` reads
`retrieved_context` from `rag_retrieve`. Implementing out of order would require stubbing state
that has not been defined yet, and would produce misleading test results.

**FastAPI service after the full workflow** — the API layer is a thin wrapper around the workflow.
Implementing it before the workflow is complete forces the endpoint to stub or crash. Keeping it
separate also means the workflow logic can be unit-tested without HTTP overhead in earlier branches.

**Observability after functional steps** — writing `trace_events` is a side effect. If it is added
during the same branch as the business logic, a DB write failure will mask whether the step logic
itself is correct. A dedicated observability branch makes the instrumentation reviewable in
isolation and ensures that step correctness is proven before tracing is layered on.

**Testing last** — unit tests for isolated helpers can be written earlier, but integration,
end-to-end, and golden tests require the complete pipeline. Consolidating all test work into a
single branch also avoids the maintenance burden of updating tests every time a preceding step's
interface changes.
