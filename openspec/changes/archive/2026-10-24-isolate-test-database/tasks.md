## 1. Test database infrastructure

- [x] 1.1 Add `TEST_DATABASE_URL` (pointing to `travel_agent_test_db`) to `.env.example` and describe its purpose; Verify: the file contains the variable and the comment
- [x] 1.2 Add `test-db-setup` to `scripts/dev.py`: create the test database (skip if it exists) → `alembic upgrade head` → seed; Verify: two consecutive runs both succeed, the second seed output is all `[skip]` with no `[embed]`; `count-rows` against the test database shows 50 / 3 / 13

- [x] 1.3 Change the dependencies and dev dependencies in `pyproject.toml` to the versions of the actual runtime environment, change `build-backend` to `setuptools.build_meta`; convert `requirements.txt` to UTF-8 and note that pyproject is the source of truth; Verify: in a fresh venv `pip install -e ".[dev]"` succeeds, `import app.main` succeeds, and the unit tests (`-m "not integration"`, temporarily excluding `test_db_schema.py`) all pass

- [x] 1.4 `scripts/seed.py` prints the connection string with the password masked (`render_as_string(hide_password=True)`); Verify: the `test-db-setup` output shows `***` instead of the password, and host, port and database name are still visible

## 2. Test tiers and isolation

- [x] 2.1 In `tests/conftest.py`, override `DATABASE_URL` with `TEST_DATABASE_URL` before the application code is imported; when it is not set, skip `integration` and `destructive` tests with a reason; remove the `pytest.skip` checks of environment variables in individual test files; Verify: with the variable unset, `pytest -m "integration or destructive"` shows every test as skipped
- [x] 2.2 Register the `destructive` marker in `pyproject.toml`, update the description of the `integration` marker, add `addopts = "-m 'not integration and not destructive'"`; Verify: running `pytest` makes no test connect to a database or call Gemini (still all pass with the network disconnected and `TEST_DATABASE_URL` unset)
- [x] 2.3 `test_db_schema.py`: move the module-level `os.environ["DATABASE_URL"]` into the `db_engine` fixture; mark the read-only database checks `integration` and the downgrade / upgrade tests `destructive`; Verify: with no database variables set, the static checks in `pytest tests/test_db_schema.py` pass
- [x] 2.4 Add a database-name guard to the downgrade test (must end with `_test_db`); Verify: with `TEST_DATABASE_URL` temporarily pointing at the development database, the test fails and the development data is unchanged
- [x] 2.5 In `tests/conftest.py`, add an autouse fixture that makes `psycopg2.connect` fail immediately for tests without the `integration` / `destructive` marker, and set `AGNO_TELEMETRY=false` unless already set; build `DATABASE_URL` / `TEST_DATABASE_URL` in `.env.example` from the `POSTGRES_*` variables; Verify: `pytest` gives the same results as before and finishes in seconds rather than minutes; an integration test still connects to the test database

## 3. Commands

- [x] 3.1 In `scripts/dev.py`, `test` runs only the default (unit) tests; add `test-integration` (`-m integration`), `test-destructive` (`-m destructive`, running `test-db-setup` afterwards whether it passes or fails) and `test-all` (unit → integration → destructive + restore); keep the `Makefile` in sync; Verify: running `test-destructive` and then `test-integration` both pass
- [x] 3.2 Change `verify-schema` to run `pytest tests/test_db_schema.py -m "integration or destructive" -v` and then `test-db-setup`; Verify: afterwards `count-rows` on the test database is still 50 / 3 / 13

## 4. Verification and documentation

- [x] 4.1 End-to-end verification: record the development database's `count-rows` → run `dev.py test-all` → run `count-rows` again; the two results are identical and `test-all` passes completely
- [x] 4.2 Update the Running Tests section of `README.md`: the three test tiers, each command, when to run which one, and that seed data is restored automatically after `test-destructive`; Verify: following the README from scratch runs `test-all` successfully
