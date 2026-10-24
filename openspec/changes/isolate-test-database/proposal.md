# Proposal

## Why

`test_downgrade_removes_all_tables` and `test_upgrade_head_reapplies_cleanly` in `tests/test_db_schema.py` run `alembic downgrade base` / `upgrade head` directly against the development database in `.env`. Every full test run empties `itinerary_categories` and `prompt_templates`; the `DROP EXTENSION vector CASCADE` in migration 0001 also drops the `embedding` column of `ai.travel_docs`. As a result, the golden / observability integration tests that run afterwards all fail, and the development environment has to be re-seeded. The later `rebuild-rag` change will embed hundreds of text chunks and run evaluation experiments repeatedly, so this problem must be solved first.

## What Changes

- Tests use a separate test database (`TEST_DATABASE_URL`) and no longer touch the development database.
- The destructive migration tests run only against the test database; when no test database is configured they are skipped with a reason instead of falling through to the development database.
- One command creates, migrates and seeds the test database.
- Tests are split into three tiers: unit / integration (`integration`) / destructive (`destructive`). Running plain `pytest` runs only unit tests; integration and destructive tests are run with separate commands, and the seed data is restored automatically after the destructive tests.
- The Running Tests section of the README is updated to the new workflow.
- Fix `pyproject.toml`: align dependency versions with the actual runtime environment (`requirements.txt`) (they were versions that had never been installed, such as `agno==1.7.4`, while the code uses the Agno 2.x API), and change `build-backend` to the valid `setuptools.build_meta`; convert `requirements.txt` from UTF-16 to UTF-8 and note that pyproject is the source of truth. Otherwise running `dev.py install` as the README says does not produce a working environment.

## Capabilities

### New Capabilities

(None)

### Modified Capabilities

(None. This is a test-infrastructure change that does not alter the system's external behaviour, so `.openspec.yaml` sets `skip_specs: true`.)

## Impact

- `tests/conftest.py`, `tests/test_db_schema.py`, and every test marked `integration`
- `pyproject.toml` (markers and `addopts`; dependency versions and `build-backend`), `requirements.txt` (encoding), `scripts/dev.py` (new test-database and tiered-test commands; `test` / `verify-schema` changed), `Makefile`, `.env.example`, `docker-compose.yml` (may need to initialise a second database)
- **Impact on later changes**: running plain `pytest` no longer includes the golden and migration tests. In later changes, tasks that involve migrations or workflow behaviour must state in their verification that `test-destructive` / `test-integration` / `test-all` is run.
- `README.md`
- **Dependencies**: should be done first; the evaluation experiments in `build-evaluation-harness` and `rebuild-rag` depend on a development database that tests do not wipe.
