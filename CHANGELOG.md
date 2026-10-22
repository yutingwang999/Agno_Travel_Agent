# Changelog

All notable changes to this project are documented here, ordered from most recent to oldest.

## [0.1.0] — 2026-10-22
- Snapshot of the current working MVP, tagged as a baseline before the project is expanded further.

---

## [Unreleased] — 2026-04-08

### feat/ui — Static frontend and `/traces` endpoint (PR #16)
- Added `GET /traces/{session_id}` endpoint returning all `trace_events` rows for a session as JSON, ordered by `created_at`.
- Mounted a static HTML/JS frontend at `/` that calls `/generate` and displays the SSE stream and trace data.
- API routes take precedence over the static mount.

### feat/testing — Golden test, template version override, BudgetLevel enum, output guardrail (PR #15)
- Added golden test (`test_golden.py`) that runs the full end-to-end workflow against a fixed input and asserts the output matches a known-good snapshot.
- Introduced `template_version` query parameter on `POST /generate` so a specific prompt template version can be pinned for reproducibility.
- Added `BudgetLevel` enum to `TravelRequest` replacing the free-form budget string.
- Added output guardrail that rejects LLM responses missing required itinerary fields before the retry loop in `validate_output`.

---

## 2026-04-07

### feat/observability — Per-step trace writes to `trace_events` (PR #14)
- Added `TraceLogger` that writes a row to the `trace_events` table at the start and end of each workflow step.
- Recorded fields: `session_id`, `step_name`, `status` (`running` / `completed` / `failed`), `latency_ms`, `prompt_template_key`, `prompt_template_version`, `degraded_mode`, `error_type`.
- `generate` step writes the resolved template key and version alongside the trace row.

### feat/fastapi-service — `POST /generate` SSE endpoint (PR #13)
- Implemented `POST /generate` that executes the Agno workflow synchronously and streams results as `text/event-stream`.
- Each SSE event is a JSON object: `{ session_id, step, status, timestamp, data, error }`.
- Added stdout capture to collect the `retrieval_decision` evaluator's print-emitted SSE event and merge it into the sorted stream.
- Events are sorted into canonical workflow order before streaming: `intake → cag_match → retrieval_decision → rag_retrieve → generate → validate_output`.

### feat/validate-output — Step 6: Pydantic validation and retry logic (PR #12)
- Implemented `validate_output` executor that parses the LLM response against a `TravelItinerary` Pydantic schema.
- On validation failure, retries the LLM call once with an error-correction prompt before raising.

### feat/generate — Step 5: DB prompt template resolution and LLM call (PR #11)
- Implemented `generate` executor that resolves the prompt template from the `prompt_templates` table (by key and optional version).
- Calls Gemini via the Agno model interface, passing the resolved template and `additional_data` context.
- Falls back to the active template version when no version is pinned.

### fix/db-seed — CAG matcher 50-row reference dataset (PR #10)
- Seeded the `itinerary_categories` table with a 50-row reference dataset of labelled travel intent examples.
- Fixed the CAG matcher to use the seeded embeddings for cosine-similarity classification.

### feat/rag-retrieve — Step 4: RAG retrieve with Agno Knowledge and PgVector (PR #9)
- Implemented `rag_retrieve` executor using Agno's `PgVectorKnowledgeBase` to retrieve top-k travel documents.
- Migrated embedding dependency from `google-generativeai` to `google-genai`.
- Embedded `source_documents` rows are stored in the `ai.travel_docs` table managed by Agno/PgVector.

---

## 2026-04-06

### feat/retrieval-decision — Step 3: Confidence threshold routing (PR #8)
- Implemented `retrieval_decision` evaluator that reads the CAG match confidence score from `additional_data`.
- Returns `True` (run `rag_retrieve`) when confidence is below the 0.85 threshold, `False` otherwise.
- Wrapped in an Agno `Condition` node so the RAG step is skipped for high-confidence matches.

### feat/cag-match — Step 2: Embedding-based intent classification (PR #7)
- Implemented `cag_match` executor using Gemini embeddings to classify the user's travel request into one of the seeded `itinerary_categories`.
- Returns the best-matching category label and a cosine-similarity confidence score passed downstream via `additional_data`.

### feat/intake — Step 1: Input validation and normalisation (PR #6)
- Implemented `intake` executor with a `TravelRequest` Pydantic model: `destination`, `trip_length`, `budget`, `travel_style`.
- Normalises destination casing and clamps `trip_length` to a valid range before passing data downstream.

### feat/workflow-skeleton — Agno workflow skeleton with SSE stubs (PR #5)
- Defined the `travel_workflow` Agno `Workflow` with all 6 steps registered in order.
- Step executors were stubs emitting placeholder SSE events; subsequent branches replaced each stub.
- Added merge-checklist tests (`test_workflow_skeleton.py`) asserting the step registry is correct.

### feat/db-seed — Idempotent seed pipeline (PR #4)
- Added `scripts/seed.py` with an idempotent upsert pipeline for `itinerary_categories`, `prompt_templates`, and `source_documents`.
- Added `make seed` / `python scripts/dev.py seed` target.
- Added `make count-rows` / `python scripts/dev.py count-rows` target reporting row counts and embedding coverage per table.

### feat/db-schema — Alembic migrations and SQLAlchemy models (PR #3)
- Added four SQLAlchemy models: `ItineraryCategory`, `PromptTemplate`, `SourceDocument`, `TraceEvent`.
- Added Alembic migration environment and initial migration creating all tables.
- Added `verify-schema` dev task: `up → pg_isready → migrate → test_db_schema`.

### feat/project-scaffold — FastAPI entrypoint and Docker setup (PR #2)
- Initialised `src/app/main.py` with a `FastAPI` app and `GET /health` liveness probe.
- Added `docker-compose.yml` running Postgres with the `pgvector` extension.
- Added `pyproject.toml` with `[dev]` extras, and the cross-platform `scripts/dev.py` task runner.
- Added `Makefile` as a thin wrapper delegating to `scripts/dev.py`.

---

## 2026-04-05

### init/agent-foundation — Foundation documentation (PR #1)
- Added `DESIGN.md`, `git-workflow.md`, and initial architecture documentation covering the 6-step CAG + RAG workflow design.
