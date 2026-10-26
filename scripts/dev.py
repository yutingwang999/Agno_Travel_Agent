"""
Cross-platform dev task runner (Windows + macOS/Linux).

Usage:
    python scripts/dev.py up
    python scripts/dev.py down
    python scripts/dev.py install
    python scripts/dev.py migrate
    python scripts/dev.py check-health
    python scripts/dev.py test              # unit tests only (pytest default)
    python scripts/dev.py test-db-setup     # create + migrate + seed the test database
    python scripts/dev.py test-integration  # -m integration (test database + Gemini)
    python scripts/dev.py test-destructive  # -m destructive, then re-seed the test database
    python scripts/dev.py test-all          # unit -> integration -> destructive + re-seed
    python scripts/dev.py eval-db-setup     # create + migrate + seed the evaluation database
    python scripts/dev.py verify
    python scripts/dev.py verify-schema
"""

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Destructive tests refuse any other database name (see tests/test_db_schema.py).
TEST_DB_SUFFIX = "_test_db"

# The evaluation database must be neither the development nor the test database.
EVAL_DB_SUFFIX = "_eval_db"

# Knowledge-base table for each corpus version in the evaluation database.
# v1 = the 13 handwritten v0.1.0 documents in scripts/seed.py.
EVAL_KNOWLEDGE_TABLES = {"v1": "travel_docs_v1"}

DEFAULT_KNOWLEDGE_TABLE = "travel_docs"


def load_env() -> None:
    """Load .env without overriding variables already set in the shell."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT_DIR, ".env"), override=False)
    except ImportError:
        pass


def run(cmd: list[str], check: bool = True, env: dict | None = None) -> int:
    merged_env = {**os.environ, **(env or {})}
    sys.stdout.flush()  # keep our headings in order with the subprocess output
    result = subprocess.run(cmd, env=merged_env)
    if check and result.returncode != 0:
        print(f"ERROR: command failed: {' '.join(cmd)}")
        sys.exit(result.returncode)
    return result.returncode


def up():
    print("--- starting postgres ---")
    run(["docker", "compose", "up", "-d"])


def down():
    print("--- stopping postgres ---")
    run(["docker", "compose", "down"])


def install():
    print("--- installing dependencies ---")
    run([sys.executable, "-m", "pip", "install", "-e", ".[dev]"])


def migrate():
    print("--- running alembic upgrade head ---")
    run([sys.executable, "-m", "alembic", "upgrade", "head"])


def check_health(retries: int = 5, delay: float = 1.0):
    print("--- checking health endpoint ---")
    url = "http://localhost:8000/health"
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    print(f"health check passed: {resp.read().decode()}")
                    return
        except (urllib.error.URLError, OSError):
            print(f"attempt {attempt}/{retries} failed, retrying...")
            time.sleep(delay)
    print("ERROR: health check failed after all retries")
    sys.exit(1)


def test():
    print("--- running unit tests ---")
    if not os.environ.get("TEST_DATABASE_URL"):
        print(
            "note: TEST_DATABASE_URL is not set, so integration and destructive tests "
            "will be skipped (see .env.example)"
        )
    run([sys.executable, "-m", "pytest"])


def required_database_url(variable: str, suffix: str) -> str:
    """Return the URL in `variable`, exiting if it is unset or its database lacks `suffix`."""
    from sqlalchemy import make_url

    url = os.environ.get(variable)
    if not url:
        print(f"ERROR: {variable} not set - add it to .env (see .env.example)")
        sys.exit(1)
    name = make_url(url).database or ""
    if not name.endswith(suffix):
        print(f"ERROR: {variable} database {name!r} must end with {suffix!r}")
        sys.exit(1)
    return url


def test_database_url() -> str:
    """Return TEST_DATABASE_URL, exiting if it is unset or not a *_test_db database."""
    return required_database_url("TEST_DATABASE_URL", TEST_DB_SUFFIX)


def create_database_if_missing(database_url: str) -> None:
    """Create the database named in database_url on the same server, if absent."""
    from sqlalchemy import create_engine, make_url, text

    url = make_url(database_url)
    server = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        ).scalar()
        if exists:
            print(f"database {url.database} already exists")
        else:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            print(f"created database {url.database}")
    server.dispose()


def migrate_database(database_url: str) -> None:
    print("--- running alembic upgrade head ---")
    run([sys.executable, "-m", "alembic", "upgrade", "head"], env={"DATABASE_URL": database_url})


def test_db_setup():
    """Create (if missing), migrate and seed the test database. Safe to re-run."""
    url = test_database_url()
    print("--- preparing test database ---")
    create_database_if_missing(url)
    migrate_database(url)
    print("--- running seed script against the test database ---")
    run([sys.executable, "scripts/seed.py"], env={"DATABASE_URL": url})
    count_rows(url)


def test_integration():
    print("--- running integration tests ---")
    test_database_url()
    run([sys.executable, "-m", "pytest", "-m", "integration"])


def test_destructive():
    """Run the migration tests, then restore the test database whatever the outcome."""
    print("--- running destructive tests ---")
    test_database_url()
    code = run([sys.executable, "-m", "pytest", "-m", "destructive"], check=False)
    print("--- restoring test database ---")
    test_db_setup()
    if code != 0:
        print("ERROR: destructive tests failed")
        sys.exit(code)


def test_all():
    """Full check before merging: unit -> integration -> destructive + restore."""
    test()
    test_integration()
    test_destructive()
    print("--- all test tiers passed ---")


def eval_db_setup():
    """Create (if missing), migrate and seed the evaluation database. Safe to re-run.

    Categories and templates go into the usual tables; each corpus version's
    documents go into its own knowledge-base table (EVAL_KNOWLEDGE_TABLES).
    """
    url = required_database_url("EVAL_DATABASE_URL", EVAL_DB_SUFFIX)
    print("--- preparing evaluation database ---")
    create_database_if_missing(url)
    migrate_database(url)
    for corpus, table in EVAL_KNOWLEDGE_TABLES.items():
        print(f"--- running seed script against the evaluation database (corpus {corpus}) ---")
        run(
            [sys.executable, "scripts/seed.py"],
            env={"DATABASE_URL": url, "KNOWLEDGE_TABLE_NAME": table},
        )
        count_rows(url, knowledge_table=table)


def verify():
    src_path = os.path.join(os.path.dirname(__file__), "..", "src")
    src_path = os.path.abspath(src_path)

    up()

    print("--- waiting for postgres ---")
    run([
        "docker", "compose", "exec", "postgres",
        "pg_isready",
        "-U", os.environ.get("POSTGRES_USER", "travel_agent"),
        "-d", os.environ.get("POSTGRES_DB", "travel_agent_db"),
    ])

    migrate()

    print("--- starting uvicorn ---")
    uvicorn_env = {"PYTHONPATH": src_path}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        env={**os.environ, **uvicorn_env},
    )

    try:
        time.sleep(3)
        check_health()
        test()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    print("--- all checks passed ---")


def seed():
    print("--- running seed script ---")
    run([sys.executable, "scripts/seed.py"])


def count_rows(database_url: str | None = None, knowledge_table: str | None = None):
    """Print row counts for all seeded tables (DATABASE_URL unless a URL is given).

    The knowledge-base table is KNOWLEDGE_TABLE_NAME (default travel_docs)
    unless one is given.
    """
    src_dir = os.path.join(ROOT_DIR, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    knowledge_table = (
        knowledge_table or os.environ.get("KNOWLEDGE_TABLE_NAME") or DEFAULT_KNOWLEDGE_TABLE
    )
    knowledge_label = f"ai.{knowledge_table}"

    from sqlalchemy import create_engine, make_url, text

    engine = create_engine(database_url)
    tables = ["itinerary_categories", "prompt_templates", "source_documents", "trace_events"]

    embedded_tables = ["itinerary_categories", "source_documents"]

    print(f"--- row counts ({make_url(database_url).database}) ---")
    with engine.connect() as conn:
        for table in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:<30} {count}")

        # Agno-managed knowledge base table (ai schema) — created by PgVector on first seed
        try:
            count = conn.execute(text(f'SELECT COUNT(*) FROM ai."{knowledge_table}"')).scalar()
            print(f"  {knowledge_label:<30} {count}")
        except Exception:
            print(f"  {knowledge_label:<30} (not yet created — run: python scripts/dev.py seed)")

    print("--- embedding coverage ---")
    with engine.connect() as conn:
        for table in embedded_tables:
            total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            null_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE embedding_vector IS NULL")
            ).scalar()
            status = "OK" if null_count == 0 else f"WARNING: {null_count} null vector(s)"
            print(f"  {table:<30} {total - null_count}/{total} have embeddings  [{status}]")

        # Agno knowledge base — check embedding coverage
        try:
            total = conn.execute(text(f'SELECT COUNT(*) FROM ai."{knowledge_table}"')).scalar()
            null_count = conn.execute(
                text(f'SELECT COUNT(*) FROM ai."{knowledge_table}" WHERE embedding IS NULL')
            ).scalar()
            status = "OK" if null_count == 0 else f"WARNING: {null_count} null vector(s)"
            print(f"  {knowledge_label:<30} {total - null_count}/{total} have embeddings  [{status}]")
        except Exception:
            pass


def verify_schema():
    """db-schema checklist on the test database, then restore its seed data."""
    url = test_database_url()
    up()

    print("--- waiting for postgres ---")
    run([
        "docker", "compose", "exec", "postgres",
        "pg_isready",
        "-U", os.environ.get("POSTGRES_USER", "travel_agent"),
        "-d", os.environ.get("POSTGRES_DB", "travel_agent_db"),
    ])

    create_database_if_missing(url)
    migrate_database(url)

    print("--- running db-schema tests ---")
    code = run(
        [sys.executable, "-m", "pytest", "tests/test_db_schema.py",
         "-m", "integration or destructive", "-v"],
        check=False,
    )
    print("--- restoring test database ---")
    test_db_setup()
    if code != 0:
        print("ERROR: db-schema tests failed")
        sys.exit(code)

    print("--- db-schema checklist passed ---")


COMMANDS = {
    "up": up,
    "down": down,
    "install": install,
    "migrate": migrate,
    "seed": seed,
    "count-rows": count_rows,
    "check-health": check_health,
    "test": test,
    "test-db-setup": test_db_setup,
    "test-integration": test_integration,
    "test-destructive": test_destructive,
    "test-all": test_all,
    "eval-db-setup": eval_db_setup,
    "verify": verify,
    "verify-schema": verify_schema,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python scripts/dev.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    load_env()
    COMMANDS[sys.argv[1]]()
