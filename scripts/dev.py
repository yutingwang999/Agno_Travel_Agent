"""
Cross-platform dev task runner (Windows + macOS/Linux).

Usage:
    python scripts/dev.py up
    python scripts/dev.py down
    python scripts/dev.py install
    python scripts/dev.py migrate
    python scripts/dev.py check-health
    python scripts/dev.py test
    python scripts/dev.py verify
    python scripts/dev.py verify-schema
"""

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error


def run(cmd: list[str], check: bool = True, env: dict | None = None) -> int:
    merged_env = {**os.environ, **(env or {})}
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
    print("--- running pytest ---")
    run([sys.executable, "-m", "pytest"])


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


def count_rows():
    """Print row counts for all seeded tables."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_dir = os.path.join(root_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # Load .env so DATABASE_URL is available without requiring it in the shell
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(root_dir, ".env"))
    except ImportError:
        pass

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    tables = ["itinerary_categories", "prompt_templates", "source_documents", "trace_events"]

    embedded_tables = ["itinerary_categories", "source_documents"]

    print("--- row counts ---")
    with engine.connect() as conn:
        for table in tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:<30} {count}")

        # Agno-managed knowledge base table (ai schema) — created by PgVector on first seed
        try:
            count = conn.execute(text("SELECT COUNT(*) FROM ai.travel_docs")).scalar()
            print(f"  {'ai.travel_docs':<30} {count}")
        except Exception:
            print(f"  {'ai.travel_docs':<30} (not yet created — run: python scripts/dev.py seed)")

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
            total = conn.execute(text("SELECT COUNT(*) FROM ai.travel_docs")).scalar()
            null_count = conn.execute(
                text("SELECT COUNT(*) FROM ai.travel_docs WHERE embedding IS NULL")
            ).scalar()
            status = "OK" if null_count == 0 else f"WARNING: {null_count} null vector(s)"
            print(f"  {'ai.travel_docs':<30} {total - null_count}/{total} have embeddings  [{status}]")
        except Exception:
            pass


def verify_schema():
    """Full db-schema merge checklist: up -> pg_isready -> migrate -> test_db_schema."""
    up()

    print("--- waiting for postgres ---")
    run([
        "docker", "compose", "exec", "postgres",
        "pg_isready",
        "-U", os.environ.get("POSTGRES_USER", "travel_agent"),
        "-d", os.environ.get("POSTGRES_DB", "travel_agent_db"),
    ])

    migrate()

    print("--- running db-schema tests ---")
    run([sys.executable, "-m", "pytest", "tests/test_db_schema.py", "-v"])

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
    "verify": verify,
    "verify-schema": verify_schema,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python scripts/dev.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
