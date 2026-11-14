# Travel Itinerary Planner

An AI-powered itinerary planner for Australian destinations. A request (destination, trip length, budget, travel style, optional notes) goes through a fixed six-step Agno workflow: intent classification, retrieval from a knowledge base built mainly from Wikivoyage, generation with a versioned prompt from the database, and validation against a schema and business rules. Each step is streamed to the client as a Server-Sent Event as soon as it finishes, and each day of the itinerary cites the knowledge chunks it draws on.

Behaviour is changed through OpenSpec changes, and every change that claims a quality improvement is measured with the evaluation harness (see [Project history](#project-history)).

---

## Architecture

```
POST /generate
      │  field validation (422), input guards: prompt injection, Australian destination (422 + reason)
      ▼
Agno workflow (six plain Steps, run in a worker thread)
  1. intake              — normalise the request, resolve the destination's canonical name
  2. cag_match           — embed the request, cosine match against 50 itinerary categories
  3. retrieval_decision  — always retrieve (kept as the plug-in point for future routing)
  4. rag_retrieve        — top 5 chunks for notes + travel style + destination,
                           filtered to the destination and Australia-wide chunks
  5. generate            — prompt template itinerary_with_context from the database,
                           chunks numbered S1, S2, ...; Gemini structured output
  6. validate_output     — Pydantic schema + business rules; one correction call on failure
      │
      ▼
SSE stream: one event per step, each sent as soon as the step finishes
```

Every event has the same envelope:

```json
{
  "session_id": "...",
  "step": "rag_retrieve",
  "status": "completed",
  "timestamp": "...",
  "data": {},
  "error": null
}
```

"CAG" in this project is embedding-based intent classification, not cache-augmented generation. The matched category's preset tone and constraints are passed to the prompt; its confidence no longer decides anything. A diagram of the flow: [docs/main-logic-diagram.png](docs/main-logic-diagram.png).

---

## Tech stack

| Layer | Technology |
| --- | --- |
| API | FastAPI + sse-starlette |
| Workflow | Agno 2.x (`Workflow`, `Step`) |
| Knowledge base | Agno `Knowledge` + `PgVector` (table `ai.travel_docs`) |
| Database | PostgreSQL 16 + pgvector |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| LLM | Gemini (`LLM_MODEL`, e.g. `gemini-3.1-flash-lite`) via `google-genai` |
| Embeddings | `gemini-embedding-001`, 768 dimensions |
| Validation | Pydantic v2 |
| Evaluation judge | OpenAI model (evaluation only; the app never calls it) |

Exact versions are pinned in [pyproject.toml](pyproject.toml).

---

## Setup

Prerequisites: Python 3.11+ and Docker Desktop.

```bash
git clone <repo-url>
cd Agno_Travel_Agent
cp .env.example .env              # then fill in GEMINI_API_KEY and POSTGRES_PASSWORD

python scripts/dev.py install     # pip install -e ".[dev]"
python scripts/dev.py up          # start PostgreSQL (docker compose)
python scripts/dev.py migrate     # alembic upgrade head
python scripts/dev.py seed        # categories, prompt templates, knowledge base
```

Start the app and open http://localhost:8000:

```bash
PYTHONPATH=src uvicorn app.main:app --reload                    # macOS / Linux
$env:PYTHONPATH="src"; python -m uvicorn app.main:app --reload  # Windows PowerShell
```

**The knowledge-base corpus is not in this repository** (see [Data sources and licences](#data-sources-and-licences)). Without it, `seed` warns and leaves the knowledge base empty; the app still runs, and generates without retrieved context or citations. With the private files in `data/knowledge/`, `python scripts/build_corpus.py build` writes the corpus JSONL that `seed` loads.

Seeding is idempotent: rows that already exist are skipped before any embedding call, and document embeddings are cached in `.cache/embeddings/`.

---

## Environment variables

All variables are documented in [.env.example](.env.example).

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | PostgreSQL container settings |
| `DATABASE_URL` | Development database DSN, used by the app, Alembic and seed |
| `TEST_DATABASE_URL` | Test database; the name must end with `_test_db` |
| `EVAL_DATABASE_URL` | Evaluation database; the name must end with `_eval_db` |
| `GEMINI_API_KEY` | Generation and embeddings |
| `OPENAI_API_KEY` | Evaluation judge only |
| `LLM_MODEL` | Gemini model for generation and the correction call |
| `EMBEDDING_MODEL` | Embedding model; must be the same for seed and runtime (default `gemini-embedding-001`) |
| `KNOWLEDGE_TABLE_NAME` | Knowledge-base table in the `ai` schema (default `travel_docs`) |
| `KNOWLEDGE_CORPUS` | Corpus JSONL file that seed loads (default `data/knowledge/corpus_c800_o80.jsonl`), or `v1` |
| `KNOWLEDGE_TASK_TYPES` | Embedding task types of the table: `retrieval` (default) or `semantic` (the v1 tables) |
| `APP_HOST`, `APP_PORT` | Uvicorn bind host and port |

Changing `EMBEDDING_MODEL`, `KNOWLEDGE_CORPUS` or `KNOWLEDGE_TASK_TYPES` invalidates stored vectors. Seed drops and rebuilds a knowledge-base table that holds anything other than the current corpus file.

---

## Dev commands

`scripts/dev.py` is a cross-platform task runner; on macOS / Linux `make <target>` wraps it.

```bash
python scripts/dev.py up | down        # start / stop PostgreSQL
python scripts/dev.py install          # pip install -e ".[dev]"
python scripts/dev.py migrate          # alembic upgrade head
python scripts/dev.py seed             # categories, prompt templates, knowledge base (idempotent)
python scripts/dev.py count-rows       # row counts + embedding coverage
python scripts/dev.py check-health     # GET /health -> 200
python scripts/dev.py test             # unit tests
python scripts/dev.py test-db-setup    # create + migrate + seed the test database
python scripts/dev.py test-integration # integration + golden tests on the test database
python scripts/dev.py test-destructive # migration tests, then re-seed the test database
python scripts/dev.py test-all         # unit -> integration -> destructive
python scripts/dev.py verify           # up -> migrate -> uvicorn -> health + unit tests
python scripts/dev.py verify-schema    # db-schema tests on the test database, then re-seed
python scripts/dev.py eval-db-setup    # create + migrate + seed the evaluation database
```

---

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness probe |
| `POST /generate` | Run the workflow and stream one SSE event per step |
| `GET /traces/{session_id}` | The trace rows of one request |
| `GET /` | The browser UI |

```bash
curl -N -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "cultural", "notes": "We love museums"}'
```

| Field | Required | Values |
| --- | --- | --- |
| `destination` | yes | One Australian place, in English or Chinese (`"悉尼"`); replaced by its canonical English name |
| `trip_length` | yes | 1–14 days |
| `budget` | yes | `"budget"`, `"moderate"` or `"luxury"` |
| `travel_style` | yes | Free text |
| `max_daily_budget_aud` | no | Whole AUD per person per day, excluding accommodation |
| `notes` | no | Free text for details the other fields cannot express, at most 500 characters |

Query parameter `template_version=N` pins a version of the generation template instead of the active one.

- **Budget.** Costs are AUD per person, excluding accommodation. The daily ceiling is `max_daily_budget_aud` when given, otherwise the level's default: `budget` 70, `moderate` 200, `luxury` none.
- **Input guards.** A free-text field that looks like a prompt injection is refused with `input_rejected`; a destination that is not one place in the Australian place list (`data/places/australia.tsv`) is refused with `destination_out_of_scope`. Both are 422 with a `reason` code, and no workflow step runs.
- **Streaming.** Events arrive in workflow order, each as soon as its step finishes; other requests are answered while a workflow runs. If the client disconnects, the running step finishes and no later step starts.

The full reference — every step's `data`, the itinerary and citation shapes, error bodies and what each failure looks like in the stream — is [docs/api.md](docs/api.md).

---

## How it works

### Retrieval

The knowledge base is corpus v2: Wikivoyage city pages at pinned revisions, plus the Australia-wide handwritten documents of v0.1.0, split into 800-character chunks with 80 characters of overlap and embedded with the `retrieval` task types. `rag_retrieve` searches it through Agno `Knowledge` + `PgVector` with the query "notes + travel style + destination", keeps chunks tagged with the destination or as Australia-wide, and returns the top 5. Any error in embedding or search is logged and the step completes with no chunks.

BM25 + RRF, Agno hybrid search and Cross-Encoder reranking were measured and not adopted; [docs/experiments.md](docs/experiments.md) records the comparisons.

### Generation and prompts

`generate` uses one template, `itinerary_with_context`, read from the `prompt_templates` table (the active version, or the one pinned with `?template_version=N`). Each retrieved chunk is written into the prompt as `[S1] <title>`, `[S2] ...`, and the model lists for each day the ids it draws on. The call asks Gemini for JSON with `ItineraryOutput` as the response schema.

Prompts are never edited in place: a change is a new entry in `TEMPLATE_DEFINITIONS` in `scripts/seed.py`, and `ACTIVE_TEMPLATE_VERSIONS` there decides which version of each key is active. A partial unique index allows one active version per key. The template version used is in the `generate` event and the trace.

### Validation

`validate_output` validates the output against `ItineraryOutput` (destination, trip length, budget level, travel style, daily items with morning / afternoon / evening, cost and `sources`, total cost, tips), then checks the business rules in `workflow/business_rules.py`:

- the day count matches the request;
- daily costs add up to the total (± max(1 AUD, 1%));
- the total is within the daily ceiling × days;
- opening hours and prices in the text appear in the retrieved context;
- every cited id is one of the chunks placed in the prompt.

On failure it makes one correction call with the `validate_output_correction` template and marks the result `degraded_mode`. If the correction also fails, the event has `status: "error"`; the workflow never raises.

### Tracing

Every exit path of every step writes one row to `trace_events`: step, status, latency, template key and version, input and output tokens, `degraded_mode` and `error_type`. Trace writes swallow database errors. `GET /traces/{session_id}` returns the rows of one request, and the UI shows them after each run.

---

## Browser UI

`GET /` serves `src/app/static/index.html` (plain HTML and JavaScript, no build step):

- a form with the request fields, notes, and an optional template version;
- three presets (Sydney family trip, Melbourne budget trip, and Alice Springs with an unusual style);
- one panel per workflow step, filled in as its event arrives;
- the itinerary with each day's sources, Wikivoyage sources linked to their section, and the licence notice;
- the trace table for the request.

To start with an empty trace table: `TRUNCATE TABLE trace_events RESTART IDENTITY;` on the development database.

---

## Tests

Tests never touch the development database: `tests/conftest.py` replaces `DATABASE_URL` with `TEST_DATABASE_URL` (`travel_agent_test_db`, same container) before the app is imported.

| Tier | Marker | Needs | Command |
| --- | --- | --- | --- |
| Unit | none | nothing; database and LLM are faked | `python -m pytest` or `python scripts/dev.py test` |
| Integration | `integration` | seeded test database + `GEMINI_API_KEY`; costs API calls | `python scripts/dev.py test-integration` |
| Destructive | `destructive` | test database; **wipes it**, then re-seeds | `python scripts/dev.py test-destructive` |

One-time setup for the integration and destructive tiers: set `TEST_DATABASE_URL` in `.env`, then `python scripts/dev.py up` and `python scripts/dev.py test-db-setup`. The test database is seeded with a small generated corpus (`tests/fixtures/knowledge/`, also not in git); without it `test-db-setup` stops with a message.

- Day to day: `python scripts/dev.py test`.
- After changing workflow behaviour: `test-integration` (golden tests and an end-to-end `POST /generate`).
- After changing a migration: `test-destructive`.
- Before merging: `test-all`.

Don't run `pytest -m ""`: the migration tests would empty the test database before the golden tests run. If `TEST_DATABASE_URL` is not set, the integration and destructive tests are skipped.

---

## Evaluation

Tests check that the code works; the evaluation measures how good the itineraries are, on a fixed dataset (`eval/dataset.jsonl`): retrieval recall and MRR, whether each request is planned, refused or should be clarified, the day and budget constraints, faithfulness to the retrieved context, citation accuracy, whether the places are in the destination, and whether the traveller's preferences are followed. The last four are decided by a judge model from another provider, calibrated against hand review.

```bash
python scripts/dev.py eval-db-setup                                    # once: create + migrate + seed travel_agent_eval_db
python scripts/eval_run.py --config <name>                             # full run -> eval/runs/<run id>/
python scripts/eval_run.py --config <name> --subset smoke              # 10 entries
python scripts/eval_compare.py <run id> <run id>                       # comparison table
python scripts/eval_gate.py                                            # smoke run against eval/thresholds.yaml
```

The evaluation has its own database (`EVAL_DATABASE_URL`), with one knowledge-base table per corpus and chunking configuration, and needs `GEMINI_API_KEY` and `OPENAI_API_KEY`. Commit before a run you want to cite: a run on uncommitted code is marked `git_dirty`.

- How to run it, read `summary.json`, calibrate the judge, and what a run costs: [docs/evaluation.md](docs/evaluation.md).
- Measured results, comparisons and threshold changes: [docs/experiments.md](docs/experiments.md).

---

## Project layout

```
.
├── src/
│   ├── app/
│   │   ├── main.py                 # FastAPI: /health, /generate, /traces/{id}, static UI
│   │   ├── static/index.html       # browser UI
│   │   ├── models/                 # SQLAlchemy models: categories, prompt templates, traces
│   │   └── workflow/
│   │       ├── travel_workflow.py  # the six-step Agno workflow
│   │       ├── steps/              # one executor per step
│   │       ├── sse.py              # SSE event builder
│   │       ├── intake_model.py     # TravelRequest
│   │       ├── input_guard.py      # prompt-injection and destination guards
│   │       ├── places.py           # Australian place list lookup
│   │       ├── cag_matcher.py      # intent classification
│   │       ├── gemini_embedder.py  # embedder shared by seed, CAG and RAG
│   │       ├── knowledge_base.py   # Knowledge + PgVector factory, task types
│   │       ├── retrieval_service.py
│   │       ├── template_resolver.py, template_versions.py
│   │       ├── output_validator.py # ItineraryOutput + parsing
│   │       ├── business_rules.py, budget.py
│   │       ├── llm_usage.py        # token usage
│   │       └── trace_logger.py
│   └── evaluation/                 # harness: dataset, runner, judge, metrics, behaviour, cost, gate, compare, calibration
├── scripts/
│   ├── dev.py                      # task runner
│   ├── seed.py                     # categories, templates, knowledge base
│   ├── build_corpus.py             # knowledge-base corpus from pinned Wikivoyage revisions
│   ├── build_places.py             # Australian place list
│   └── eval_*.py                   # run, compare, gate, re-judge, calibration, dataset check, prompt comparison
├── eval/                           # dataset, configs, subsets, judge prompts, thresholds, prices, run summaries
├── data/places/                    # Australian place list and its sources
├── alembic/versions/               # migrations 0001-0007
├── tests/
├── openspec/                       # specs (current behaviour) and changes (planned and archived)
└── docs/
```

---

## Project history

| Version / change | What it did |
| --- | --- |
| v0.1.0 | The original MVP: CAG-gated RAG (retrieval only below 0.85 confidence), two generation templates, corpus of 13 hand-written documents |
| `isolate-test-database` | Tests use their own database |
| `build-evaluation-harness` | Evaluation dataset, database, judge, metrics, comparison and gate; the v0.1.0 baseline |
| `harden-workflow-guardrails` (v0.2.0) | Input guards, structured output, business rules, per-person costs and the daily budget amount, template version management |
| `true-sse-streaming` | Each event sent as its step finishes, off the event loop |
| `rebuild-rag` (v0.3.0) | Wikivoyage corpus, retrieval on every request, one generation template, per-day citations |
| `parse-requests` (proposed) | Free-text requests parsed into the form |

Details: [CHANGELOG.md](CHANGELOG.md), [docs/roadmap.md](docs/roadmap.md), and the archived changes in `openspec/changes/archive/`.

---

## Data sources and licences

| Data | Used for | Source and licence | Details |
| --- | --- | --- | --- |
| Australian place list (`data/places/australia.tsv`) | The destination guard: which destinations are accepted, and their canonical English names | Place names from [GeoNames](https://www.geonames.org/) (`cities1000`), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), plus hand-kept lists of states, tourist destinations and Chinese names written for this project. Contains data from GeoNames (https://www.geonames.org/), licensed under CC BY 4.0. Modified: only Australian places are used, names are lowercased, and the list is combined with hand-kept lists written for this project. | [data/places/SOURCES.md](data/places/SOURCES.md) |
| Knowledge base, corpus v2 | RAG context and citations | City pages from [Wikivoyage](https://en.wikivoyage.org/), licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), at pinned revisions, plus the Australia-wide handwritten documents of corpus v1. Not in this repository: the page list, the downloaded pages and the built corpus are local files backed up privately. The UI links each cited Wikivoyage source to its page and shows the licence | [docs/evaluation.md](docs/evaluation.md), "What is published" |
| Knowledge base, corpus v1 (13 documents) | The v0.1.0 baseline in the evaluation; its Australia-wide documents are also part of corpus v2 | Handwritten for v0.1.0; not in this repository (`data/knowledge/v1/source_documents.json`, backed up privately) | [docs/evaluation.md](docs/evaluation.md) |

---

## Documentation

- [docs/api.md](docs/api.md) — API reference: requests, every step's event, errors and failure behaviour
- [docs/evaluation.md](docs/evaluation.md) — running the evaluation and calibrating the judge
- [docs/experiments.md](docs/experiments.md) — measured results
- [docs/roadmap.md](docs/roadmap.md) — planned work
- [docs/git-workflow.md](docs/git-workflow.md) — branches and "main must stay runnable"
- [openspec/specs/](openspec/specs/) — the current behaviour contract
- [docs/DESIGN.md](docs/DESIGN.md), [docs/CLAUDE.md](docs/CLAUDE.md) — the original v0.1.0 design and AI usage rules (OpenSpec takes precedence)
