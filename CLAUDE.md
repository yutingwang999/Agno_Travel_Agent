# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Travel itinerary planner for Australian destinations: FastAPI + an Agno workflow + PostgreSQL/pgvector + Gemini.

## Sources of truth

`docs/DESIGN.md` and `docs/CLAUDE.md` describe the original v0.1.0 design. The project is now deliberately changing behaviour through OpenSpec, so precedence is:

1. The OpenSpec change being implemented (`openspec/changes/<name>/`)
2. `openspec/specs/` — the current behaviour contract
3. `docs/DESIGN.md` / `docs/CLAUDE.md` — v0.1.0 background

Where an OpenSpec change contradicts DESIGN.md or the "Mandatory Architecture Constraints" in `docs/CLAUDE.md`, the change wins; don't push back on it or "restore" the v0.1.0 behaviour. Known intentional departures:

- `retrieval_decision` becomes a plain Step instead of an Agno Condition (`true-sse-streaming`).
- Retrieval runs for every request and the two generation templates merge into one (`rebuild-rag`).
- Custom retrieval code (BM25 + RRF, reranking) is allowed where the evaluation justifies it, despite "avoid custom vector search logic" (`rebuild-rag`).
- The `source_documents` table is dropped (`rebuild-rag`).

The non-structural rules in `docs/CLAUDE.md` still apply: plan before non-trivial changes, prompts live in the DB with versions, every step emits an SSE event and writes a trace, outputs are validated with Pydantic, and schema / public API changes need confirmation.

## Language

Write everything in the repository in English: code, comments, docs, OpenSpec artifacts (proposal, design, specs, tasks), roadmap, experiment records, commit messages and PR descriptions. The only exception is Chinese that is part of the product itself — e.g. Chinese place names in the destination guardrail's place-name table and the tests or scenarios that exercise them, or Chinese input in `mixed_language` evaluation entries. The conversation with the user may be in Chinese; that does not change the language of files.

## Environment

- If `.vscode/settings.json` exists (it is gitignored, so only on machines that have set it up), use the interpreter in its `python.defaultInterpreterPath`; otherwise use a Python 3.11+ environment with the dependencies from `pyproject.toml` installed. The `python` on PATH in a plain shell may be a different environment without `agno`; if imports fail, call the intended interpreter explicitly.
- **Never install, upgrade, downgrade or uninstall packages in a Python environment on your own** (`pip`, `conda`, `dev.py install`, etc.). When a task needs a package change, stop and tell the user which package, which version, why, and which environment; run it only after they confirm.
- The code targets the Agno 2.x workflow API (`from agno.workflow import Step, Condition, Workflow`). Dependencies are pinned in `pyproject.toml` (source of truth; `dev.py install` = `pip install -e ".[dev]"`); `requirements.txt` mirrors the runtime list and must be kept in sync.
- `.env` is loaded by the app, Alembic `env.py`, `scripts/seed.py` and `tests/conftest.py`. Everything reads `DATABASE_URL`; `EMBEDDING_MODEL` must be the same for seed and runtime.

## Commands

`scripts/dev.py` is the cross-platform task runner (`make <target>` wraps it on Unix):

```
python scripts/dev.py up | down          # Postgres (docker compose)
python scripts/dev.py migrate            # alembic upgrade head
python scripts/dev.py seed               # idempotent; existing rows are skipped before any embedding call
python scripts/dev.py count-rows         # row counts + embedding coverage
python scripts/dev.py test | verify | verify-schema
```

Run the app (Windows): `$env:PYTHONPATH="src"; python -m uvicorn app.main:app --reload` → UI at http://localhost:8000.

Tests (`pythonpath = ["src"]` is set in pyproject) never touch the development database: `tests/conftest.py` replaces `DATABASE_URL` with `TEST_DATABASE_URL` (`travel_agent_test_db`, same container) before the app is imported.

```
python -m pytest                                        # unit only (addopts); no DB, no API key, seconds
python -m pytest tests/test_generate.py::test_name -v   # single test
python scripts/dev.py test-db-setup                     # create + migrate + seed the test DB; idempotent
python scripts/dev.py test-integration                  # -m integration: golden etc.; costs Gemini calls
python scripts/dev.py test-destructive                  # -m destructive (downgrade/upgrade), then re-seeds -> re-embeds
python scripts/dev.py test-all                          # before merging: unit -> integration -> destructive
```

- Tiers: unmarked = unit; `integration` = needs the seeded test DB + Gemini, read-only apart from trace rows; `destructive` = wipes the test DB. Don't run `pytest -m ""` — the migration tests empty the DB before the golden tests run.
- In unit tests `psycopg2.connect` fails immediately (conftest fixture). A new test that needs a database must be marked `integration`, not given a real connection.
- Migration changes: update `tests/test_db_schema.py` (migration chain, table/column checks) and run `test-destructive`. The destructive tests refuse any database whose name doesn't end with `_test_db`.

## Architecture

`POST /generate` (`src/app/main.py`) → `travel_workflow` (`src/app/workflow/travel_workflow.py`): `intake → cag_match → retrieval_decision (Agno Condition) → [rag_retrieve] → generate → validate_output`.

Things that span several files:

- **Steps talk through serialized SSE events.** Each executor in `workflow/steps/` returns `StepOutput(content=<JSON of an SSE event>)` built with `workflow/sse.py`. Downstream steps read upstream data with `step_input.get_step_content("<step>")` and parse that JSON. Request fields and `session_id` travel in `additional_data`. Changing an event's `data` shape is therefore a contract change for later steps, for `main.py`, for the UI (`src/app/static/index.html`) and for `docs/api.md`.
- **Streaming is not real yet.** `main.py` runs the whole workflow synchronously, captures stdout to recover the `retrieval_decision` event (the Condition evaluator `print()`s it), sorts events by `_STEP_ORDER`, then emits them all at once. `true-sse-streaming` replaces this.
- **"CAG" is embedding-based intent classification**, not cache-augmented generation: `workflow/cag_matcher.py` embeds the request and does in-memory cosine similarity against the 50 `itinerary_categories` vectors. Confidence ≥ `RETRIEVAL_CONFIDENCE_THRESHOLD` (0.85, `workflow/config.py`) skips RAG and also selects the generation template.
- **Two vector stores.** Category vectors live in the Alembic-managed `itinerary_categories` table. RAG documents live in `ai.travel_docs`, created and managed by Agno `Knowledge` + `PgVector` (`workflow/knowledge_base.py`), not by Alembic. The Alembic `source_documents` table is unused legacy (`rebuild-rag` drops it). `workflow/gemini_embedder.py` is shared by seed, CAG and RAG, so changing the model or task type invalidates stored vectors.
- **Prompts come from the DB.** `template_resolver.resolve_template(key, version)` reads `prompt_templates` (active row, or the explicit `?template_version=N`); `generate._format_template` uses regex substitution because templates contain literal JSON braces. New prompt text goes in as a new entry in `TEMPLATE_DEFINITIONS` in `scripts/seed.py` (never edit an existing version), and `ACTIVE_TEMPLATE_VERSIONS` there decides which version of each key is active; a partial unique index allows one active version per key.
- **Validation + one retry.** Both LLM calls request JSON with `ItineraryOutput` as Gemini's response schema. `output_validator.parse_llm_output` strips code fences (fallback), validates `ItineraryOutput`, then runs the rules in `workflow/business_rules.py` (day count against the request, cost consistency, budget ceiling from `workflow/budget.py`, opening hours / prices not in the knowledge context) with a `ValidationContext` that `validate_output` builds from the intake and rag_retrieve events; on failure `validate_output` makes one correction call using the `validate_output_correction` template and sets `degraded_mode`.
- **Tracing never raises.** Every exit path of every step calls `trace_logger.write_trace(...)`, which swallows DB errors; rows are read back by `GET /traces/{session_id}`.

## Planning workflow (OpenSpec)

- Planned work lives in `openspec/changes/<name>/` (proposal → design → specs deltas → tasks); the current contract is in `openspec/specs/`. Use the `/opsx:*` commands / `openspec-*` skills.
- `docs/roadmap.md` fixes the archive order: `isolate-test-database` → `build-evaluation-harness` → `harden-workflow-guardrails` → `true-sse-streaming` → `rebuild-rag`. Later deltas are written against the main specs as they will be after earlier changes are archived, so don't reorder.
- `docs/roadmap/drafts/` holds drafts that are not active changes; OpenSpec ignores them.
- Quality claims need numbers: each change is measured with the evaluation harness (on its own `travel_agent_eval_db`) and recorded in `docs/experiments.md`, following the rules at the top of that file (numbers only from `eval/runs/`, append-only, record threshold changes).
- One feature branch per unit of work, merged to `main` by PR; `main` must stay runnable (see `docs/git-workflow.md`).
