# Design

## Context

- `tests/conftest.py` loads `.env` with `load_dotenv(override=False)`, so the `DATABASE_URL` the tests see is the development database.
- Every step and `scripts/seed.py` read the connection string from the `DATABASE_URL` environment variable; so does Alembic's `env.py`.
- Postgres runs in the single container defined in `docker-compose.yml`, which currently has only one database, `travel_agent_db`.

## Goals / Non-Goals

**Goals:**
- Running any test never modifies the development database.
- One command prepares a test database usable for integration tests.

**Non-Goals:**
- Do not introduce testcontainers or any other approach that starts a temporary container per test run.
- Do not change the unit tests (they already mock the database).

## Decisions

1. **Same Postgres container, a second database `travel_agent_test_db`.**
   Alternatives: another container / testcontainers. The same-container approach changes the least and starts fastest; the pgvector extension is installed per database, so the two do not affect each other.

2. **In `conftest.py`, before the application code is imported, override `DATABASE_URL` with `TEST_DATABASE_URL`.**
   This way the application code, `seed.py` and Alembic subprocesses all connect to the test database without any modification. If `TEST_DATABASE_URL` is not set: integration and migration tests are all `skip`ped with a hint on how to configure it — never fall back to the development database.

3. **Safety guard:** before running downgrade, the migration test asserts that the target database name ends with `_test_db`, and fails immediately otherwise. This prevents wiping the development database through a configuration mistake.

4. **`python scripts/dev.py test-db-setup`:** create the test database (if it does not exist) → `alembic upgrade head` → seed. Seed is idempotent (existing rows are skipped before the embedding API is called), so it can be run repeatedly at no cost.

5. **Three test tiers; only unit tests run by default.**

   | Tier | Marker | Requires | Scope |
   | --- | --- | --- | --- |
   | Unit | none | nothing (database and LLM are mocked) | most tests, plus the static checks in `test_db_schema.py` (migration file contents, migration chain, model columns) |
   | Integration | `integration` | seeded test database + Gemini key; does not alter the schema or delete seed data (does write trace rows) | golden, the integration cases in `test_cag_match` / `test_observability`, the read-only database checks in `test_db_schema.py` |
   | Destructive | `destructive` | test database; wipes data | `test_downgrade_removes_all_tables`, `test_upgrade_head_reapplies_cleanly` |

   `pyproject.toml` sets `addopts = "-m 'not integration and not destructive'"`; a `-m` on the command line overrides it. `destructive` tests are not also marked `integration`, otherwise `-m integration` would pull them in.

   Commands:

   | Scenario | pytest | dev.py / make |
   | --- | --- | --- |
   | Day to day | `pytest` | `test` (unit tests only) |
   | Prepare the test database | — | `test-db-setup` |
   | Golden and integration tests | `pytest -m integration` | `test-integration` |
   | Changed a migration | `pytest -m destructive` | `test-destructive` (runs `test-db-setup` afterwards to restore the seed data) |
   | Full check before merging | run the three above in order | `test-all`: unit → integration → destructive + restore |

   Do not use `pytest -m ""` to run everything at once: files run in alphabetical order, `test_db_schema` comes before `test_golden`, and golden would get an empty database.
   Alternative: a session-scoped fixture that checks before golden and re-seeds automatically — independent of ordering, but the migration tests wipe the database every time, so every full test run would have to re-embed, which is expensive; and the migration tests only need to run when a migration changes.

6. **Skip logic lives in conftest.** When `TEST_DATABASE_URL` is not set, `integration` and `destructive` tests are all skipped; the `pytest.skip` checks each test file wrote for itself are removed. The module-level `os.environ["DATABASE_URL"]` in `test_db_schema.py` moves into the `db_engine` fixture, so the static checks still run when it is not set.

7. **`dev.py verify-schema` explicitly runs `test_db_schema.py` with `-m "integration or destructive"` and then runs `test-db-setup`.** Otherwise, once `addopts` is added, only the static checks would be left.

8. **`pyproject.toml` is the source of truth for dependencies, with versions aligned to the actual runtime environment.** The original pins were old versions written at scaffold time and never installed (`agno==1.7.4`, while the code uses the Agno 2.x `agno.workflow` API; pytest-asyncio 0.24 → 1.3 is also a major-version gap), and `build-backend = "setuptools.backends.legacy:build"` does not exist, so `pip install -e .` fails outright. Change them to the versions in `requirements.txt` (i.e. the actual environment), and use the actually installed pytest / pytest-asyncio / httpx versions for the dev dependencies. Keep `requirements.txt` for a future Dockerfile, convert it to UTF-8 (git treats UTF-16 as binary, so diffs are unreadable), and note on its first line that it is kept in sync with pyproject.
   Alternative: delete `requirements.txt` — a Dockerfile can also run `pip install .` directly; keep it for now and decide when roadmap item 8 writes the Dockerfile.

9. **Unit tests are isolated from external services by conftest, not by each test remembering to mock everything.** About 60 unit tests reach unmocked code paths (`write_trace`, template lookups, knowledge-base access) that try to open a database connection; the result is never asserted, but every failed attempt costs ~2 s on Windows, and once `TEST_DATABASE_URL` is set some of them would really connect and write trace rows, so the same unit test behaves differently depending on whether Postgres is running. An autouse fixture replaces `psycopg2.connect` with one that fails immediately for every test without the `integration` / `destructive` marker; those two tiers connect to the test database as usual. A unit test that genuinely needs a database then fails loudly and must either mock it or be marked `integration`. conftest also sets `AGNO_TELEMETRY=false` (unless already set), because `Workflow.run` otherwise sends telemetry to `os-api.agno.com` from tests.
   Measured on the current suite: 302 s → about 3 s, same 226 results. Alternative: mock the missing calls test by test — the boundary would keep relying on every author remembering.

10. **`.env.example` builds the database URLs from `POSTGRES_*` with `${VAR}` references** instead of repeating the user, password and port, so they cannot drift apart. python-dotenv (app, tests, Alembic, seed, `dev.py`) and docker compose both expand these references.

11. **`seed.py` masks the password when it prints the connection string.** It used to print the full DSN; since `test-db-setup` (and therefore `test-destructive`, `verify-schema`, `test-all`) now runs seed every time, the password would appear in every test run's output, and `build-evaluation-harness`'s `eval-db-setup` will reuse seed too. Host, port and database name stay visible for troubleshooting.

## Risks / Trade-offs

- [Seeding the test database calls Gemini to generate embeddings, which costs money] → Seed is idempotent and only re-embeds when data is missing.
- [A developer forgets to configure `TEST_DATABASE_URL` and the integration tests are silently skipped] → State the skip reason clearly, and print a hint in `dev.py test`.

- [`integration` and `destructive` do not run by default, so broken migration or integration tests may go unnoticed] → In later changes, tasks involving migrations state in their verification that `test-destructive` is run; tasks involving workflow behaviour state that `test-integration` is run; run `test-all` before merging.
- [Integration tests write rows to the test database's `trace_events`, which keep accumulating] → Each run uses a new uuid as session_id, so results are unaffected; clear the table manually when needed.

## Open Questions

(None. How to restore data after the migration tests has been decided; see decision 5.)
