# Changelog

All notable changes to this project are documented here, most recent first. Since v0.1.0 each unit of work is an OpenSpec change; its proposal, design and tasks are in `openspec/changes/archive/`, and its measured results in `docs/experiments.md`.

## [0.3.0] — 2026-11-15

### rebuild-rag — Wikivoyage knowledge base, retrieval on every request, citations (PR #1, 2026-11-10)
- **Knowledge base corpus v2**: Wikivoyage city pages (CC BY-SA 4.0) at pinned revisions plus the Australia-wide handwritten documents of corpus v1, built by `scripts/build_corpus.py` (`pin`, `download`, `build`, `fixture`), split by section into 800-character chunks with 80 characters of overlap, with destination, section and source URL in the metadata. The corpus is never committed; the test database uses a small generated fixture corpus.
- **Retrieval**: queries and documents use the retrieval embedding task types (`KNOWLEDGE_TASK_TYPES`), and all documents were re-embedded; the query is "notes + travel style + destination" (the matched category is left out); results are filtered to the destination and Australia-wide chunks, top 5. BM25 + RRF, Agno hybrid search and Cross-Encoder reranking were measured, not adopted, and removed. Seed rebuilds a table holding another corpus, and caches document embeddings in `.cache/embeddings/`.
- **Every request retrieves** (**breaking**): `retrieval_decision` always routes to `rag_retrieve`, so `rag_retrieve` appears in every event stream; the confidence is reported only, and the `retrieval_decision` event no longer has `threshold`.
- **One generation template**, `itinerary_with_context`, replaces `high_confidence_minimal_context` and `low_confidence_with_retrieval`. Version 4 is active: the matched category's preset and the traveller's own words, the traveller's taking precedence, without invented exclusive arrangements.
- **Citations**: chunks in the prompt are numbered `S1`, `S2`, ...; each day of the itinerary lists the ids it draws on (`sources`); a business rule rejects ids that were not in the prompt; the UI shows each day's sources, Wikivoyage ones linked to their section, with the licence notice.
- `POST /generate` accepts an optional `notes` field (at most 500 characters), used in the retrieval query and the prompt; the UI has a notes box.
- **Evaluation**: dataset v3 (relabelled for corpus v2, with coverage groups); judge prompts faithfulness v2 (adds `activity` and `season` claims), destination v2, preference v1–v4 (preference adherence) and citation v1–v2 (citation accuracy); re-judging of stored runs (`scripts/eval_rejudge.py`); retrieval-only runs and chunking and embedding comparisons; per-config template version pinning; recalibration on corpus v2; the gate thresholds reset for the final configuration.
- Dropped the never-used `source_documents` table and `SourceDocument` model (migration `0007`).

### Repository moved (2026-11-04)
- The history was rewritten into a new repository so that no knowledge-base text is in git, and corpus v1 moved out of `scripts/seed.py` into a private local file. Pull request numbers restart at #1; older PR numbers below refer to the previous repository. Commit hashes recorded before this date map to the new ones through a private commit map (see `docs/experiments.md`).

### true-sse-streaming — Events sent as each step finishes (PR #22, 2026-11-01)
- `POST /generate` sends each step's event as soon as the step finishes, instead of collecting all events first; event order is unchanged.
- The workflow runs off the event loop (`iterate_in_threadpool` over Agno's `run(stream=True, stream_events=True)`), so the server answers other requests while it runs. If the client disconnects, the running step finishes and no later step starts.
- `retrieval_decision` is a plain Step instead of an Agno `Condition`; the stdout capture and `print()` used to collect its event are removed.

---

## [0.2.0] — 2026-11-01

### harden-workflow-guardrails — Error handling, structured output, business rules, input guards (PR #21)
- **Error handling**: an embedding failure falls back to the default category; a failed LLM call emits a structured error event; `validate_output` does not validate or retry after `generate` has failed; the trace records the template actually used.
- **Structured output**: generation and the correction call request JSON with `ItineraryOutput` as Gemini's response schema; code-fence stripping is kept as a fallback.
- **Business rules** after schema validation, each failure going into the one correction call: day count matches the request, daily costs add up to the total, the total is within the daily budget ceiling, and no opening hours or prices that are not in the knowledge context.
- **Budget**: costs are AUD per person, excluding accommodation, stated in every template. `POST /generate` accepts an optional `max_daily_budget_aud`; the daily ceiling is that amount, otherwise `budget` 70, `moderate` 200, `luxury` none.
- **Input guards** before the workflow, 422 with a `reason`: `input_rejected` for prompt-injection patterns in free-text fields; `destination_out_of_scope` for a destination not in the Australian place list (GeoNames `cities1000` plus hand-kept states, tourist destinations and Chinese names), including vague and two-destination requests. A match is replaced with its canonical English name.
- `trip_length` is limited to 14 days.
- **Template versions**: seed makes exactly the version declared in `ACTIVE_TEMPLATE_VERSIONS` active; migration `0006` allows one active version per key.
- Agno telemetry is off (`telemetry=False`; `AGNO_TELEMETRY` overrides it).
- The UI shows field errors and guard refusals, and has a daily budget input.
- Evaluation dataset v2 adds paired budget-amount entries.

### build-evaluation-harness — Evaluation dataset, metrics, comparison and gate (PR #20, 2026-10-28)
- Evaluation dataset of 73 labelled requests with form fields, a free-text sentence, gold slots and the expected behaviour (plan, refuse, clarify).
- Its own database, `travel_agent_eval_db` (`EVAL_DATABASE_URL`), with a configurable knowledge-base table.
- Metrics: retrieval Recall@k and MRR, behaviour, day and budget constraints, faithfulness and "places in the destination" decided by an OpenAI judge model, format pass and retry rate, per-step latency, cost per request.
- Traces record LLM input and output tokens (migration `0005`); the default generation model is `gemini-3.1-flash-lite`.
- `scripts/eval_run.py`, `eval_compare.py`, `eval_gate.py` (smoke subset against `eval/thresholds.yaml`) and stratified judge calibration with a review sheet.
- The v0.1.0 baseline was measured and recorded in `docs/experiments.md`.

### isolate-test-database — Tests use their own database (PR #19, 2026-10-25)
- Tests run against `TEST_DATABASE_URL` (`travel_agent_test_db`) and never touch the development database; destructive migration tests refuse any database whose name does not end with `_test_db`.
- Three test tiers: unit (plain `pytest`), `integration` and `destructive`, with `dev.py` commands for each and `test-db-setup` to create, migrate and seed the test database; seed data is restored after the destructive tests.
- `pyproject.toml` dependencies aligned with the environment actually used (Agno 2.x) and made the source of truth; `requirements.txt` converted to UTF-8.

### Improvement plan (PR #18, 2026-10-24)
- Added `docs/roadmap.md` and the OpenSpec changes planned after v0.1.0.

---

## [0.1.0] — 2026-10-22

Snapshot of the working MVP, tagged as a baseline before the project was expanded. The entries below are the branches that built it.

### 2026-04-08

#### feat/ui — Static frontend and `/traces` endpoint (PR #16)
- Added `GET /traces/{session_id}` endpoint returning all `trace_events` rows for a session as JSON, ordered by `created_at`.
- Mounted a static HTML/JS frontend at `/` that calls `/generate` and displays the SSE stream and trace data.
- API routes take precedence over the static mount.

#### feat/testing — Golden test, template version override, BudgetLevel enum, output guardrail (PR #15)
- Added golden test (`test_golden.py`) that runs the full end-to-end workflow against a fixed input and asserts the output matches a known-good snapshot.
- Introduced `template_version` query parameter on `POST /generate` so a specific prompt template version can be pinned for reproducibility.
- Added `BudgetLevel` enum to `TravelRequest` replacing the free-form budget string.
- Added output guardrail that rejects LLM responses missing required itinerary fields before the retry loop in `validate_output`.

### 2026-04-07

#### feat/observability — Per-step trace writes to `trace_events` (PR #14)
- Added `TraceLogger` that writes a row to the `trace_events` table at the start and end of each workflow step.
- Recorded fields: `session_id`, `step_name`, `status` (`running` / `completed` / `failed`), `latency_ms`, `prompt_template_key`, `prompt_template_version`, `degraded_mode`, `error_type`.
- `generate` step writes the resolved template key and version alongside the trace row.

#### feat/fastapi-service — `POST /generate` SSE endpoint (PR #13)
- Implemented `POST /generate` that executes the Agno workflow synchronously and streams results as `text/event-stream`.
- Each SSE event is a JSON object: `{ session_id, step, status, timestamp, data, error }`.
- Added stdout capture to collect the `retrieval_decision` evaluator's print-emitted SSE event and merge it into the sorted stream.
- Events are sorted into canonical workflow order before streaming: `intake → cag_match → retrieval_decision → rag_retrieve → generate → validate_output`.

#### feat/validate-output — Step 6: Pydantic validation and retry logic (PR #12)
- Implemented `validate_output` executor that parses the LLM response against a `TravelItinerary` Pydantic schema.
- On validation failure, retries the LLM call once with an error-correction prompt before raising.

#### feat/generate — Step 5: DB prompt template resolution and LLM call (PR #11)
- Implemented `generate` executor that resolves the prompt template from the `prompt_templates` table (by key and optional version).
- Calls Gemini via the Agno model interface, passing the resolved template and `additional_data` context.
- Falls back to the active template version when no version is pinned.

#### fix/db-seed — CAG matcher 50-row reference dataset (PR #10)
- Seeded the `itinerary_categories` table with a 50-row reference dataset of labelled travel intent examples.
- Fixed the CAG matcher to use the seeded embeddings for cosine-similarity classification.

#### feat/rag-retrieve — Step 4: RAG retrieve with Agno Knowledge and PgVector (PR #9)
- Implemented `rag_retrieve` executor using Agno's `PgVectorKnowledgeBase` to retrieve top-k travel documents.
- Migrated embedding dependency from `google-generativeai` to `google-genai`.
- Embedded `source_documents` rows are stored in the `ai.travel_docs` table managed by Agno/PgVector.

### 2026-04-06

#### feat/retrieval-decision — Step 3: Confidence threshold routing (PR #8)
- Implemented `retrieval_decision` evaluator that reads the CAG match confidence score from `additional_data`.
- Returns `True` (run `rag_retrieve`) when confidence is below the 0.85 threshold, `False` otherwise.
- Wrapped in an Agno `Condition` node so the RAG step is skipped for high-confidence matches.

#### feat/cag-match — Step 2: Embedding-based intent classification (PR #7)
- Implemented `cag_match` executor using Gemini embeddings to classify the user's travel request into one of the seeded `itinerary_categories`.
- Returns the best-matching category label and a cosine-similarity confidence score passed downstream via `additional_data`.

#### feat/intake — Step 1: Input validation and normalisation (PR #6)
- Implemented `intake` executor with a `TravelRequest` Pydantic model: `destination`, `trip_length`, `budget`, `travel_style`.
- Normalises destination casing and clamps `trip_length` to a valid range before passing data downstream.

#### feat/workflow-skeleton — Agno workflow skeleton with SSE stubs (PR #5)
- Defined the `travel_workflow` Agno `Workflow` with all 6 steps registered in order.
- Step executors were stubs emitting placeholder SSE events; subsequent branches replaced each stub.
- Added merge-checklist tests (`test_workflow_skeleton.py`) asserting the step registry is correct.

#### feat/db-seed — Idempotent seed pipeline (PR #4)
- Added `scripts/seed.py` with an idempotent upsert pipeline for `itinerary_categories`, `prompt_templates`, and `source_documents`.
- Added `make seed` / `python scripts/dev.py seed` target.
- Added `make count-rows` / `python scripts/dev.py count-rows` target reporting row counts and embedding coverage per table.

#### feat/db-schema — Alembic migrations and SQLAlchemy models (PR #3)
- Added four SQLAlchemy models: `ItineraryCategory`, `PromptTemplate`, `SourceDocument`, `TraceEvent`.
- Added Alembic migration environment and initial migration creating all tables.
- Added `verify-schema` dev task: `up → pg_isready → migrate → test_db_schema`.

#### feat/project-scaffold — FastAPI entrypoint and Docker setup (PR #2)
- Initialised `src/app/main.py` with a `FastAPI` app and `GET /health` liveness probe.
- Added `docker-compose.yml` running Postgres with the `pgvector` extension.
- Added `pyproject.toml` with `[dev]` extras, and the cross-platform `scripts/dev.py` task runner.
- Added `Makefile` as a thin wrapper delegating to `scripts/dev.py`.

### 2026-04-05

#### init/agent-foundation — Foundation documentation (PR #1)
- Added `DESIGN.md`, `git-workflow.md`, and initial architecture documentation covering the 6-step CAG + RAG workflow design.
