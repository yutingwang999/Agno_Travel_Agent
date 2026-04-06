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
