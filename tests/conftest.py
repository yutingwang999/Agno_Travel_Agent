"""Shared pytest configuration.

Loads the project .env file before any test runs so that GEMINI_API_KEY and
other required variables are available to integration tests without requiring
the caller to export them manually.

Variables already set in the shell are NOT overridden (override=False).

Database isolation: DATABASE_URL is replaced with TEST_DATABASE_URL *before*
any application code is imported, so the app, scripts/seed.py and Alembic
subprocesses all connect to the test database. Tests never fall back to the
development database: when TEST_DATABASE_URL is unset, DATABASE_URL points at
an unreachable placeholder and `integration` / `destructive` tests are skipped.

Unit tests (no `integration` / `destructive` marker) never reach a database at
all: psycopg2.connect fails immediately for them.
"""

import os
import sys

import pytest
from dotenv import load_dotenv

# Resolve .env relative to the project root (one level above tests/)
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_FILE, override=False)

# Nothing listens on port 9 locally, so an accidental connection fails fast
# instead of reaching the development database.
_UNSET_DATABASE_URL = "postgresql://unset:unset@127.0.0.1:9/test_database_url_not_set"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or _UNSET_DATABASE_URL

# Workflow.run otherwise sends telemetry to os-api.agno.com from every test.
os.environ.setdefault("AGNO_TELEMETRY", "false")

_DB_TIERS = ("integration", "destructive")

_SETUP_HINT = (
    "set TEST_DATABASE_URL in .env (see .env.example), then run "
    "`python scripts/dev.py test-db-setup`"
)


def pytest_collection_modifyitems(config, items):
    """Skip tests whose marker requires resources that are not configured."""
    missing_db = not TEST_DATABASE_URL
    missing_key = not os.environ.get("GEMINI_API_KEY")

    skip_integration = None
    if missing_db:
        skip_integration = pytest.mark.skip(reason=f"TEST_DATABASE_URL not set - {_SETUP_HINT}")
    elif missing_key:
        skip_integration = pytest.mark.skip(reason="GEMINI_API_KEY not set (see .env.example)")

    skip_destructive = (
        pytest.mark.skip(reason=f"TEST_DATABASE_URL not set - {_SETUP_HINT}") if missing_db else None
    )

    for item in items:
        if skip_integration and "integration" in item.keywords:
            item.add_marker(skip_integration)
        if skip_destructive and "destructive" in item.keywords:
            item.add_marker(skip_destructive)


@pytest.fixture(autouse=True)
def _no_database_in_unit_tests(request, monkeypatch):
    """Unit tests must not reach a database: any connection attempt fails at once.

    Unmocked side paths (trace writes, template lookups) already tolerate a
    failed connection; failing immediately keeps unit tests fast and identical
    whether or not Postgres is running. A unit test that really needs a
    database fails loudly here and should be marked `integration`.
    """
    if any(request.node.get_closest_marker(tier) for tier in _DB_TIERS):
        return

    import psycopg2

    def _refuse(*args, **kwargs):
        raise psycopg2.OperationalError(
            "unit tests must not connect to a database; "
            "mock the call or mark the test `integration`"
        )

    monkeypatch.setattr(psycopg2, "connect", _refuse)


# Redirect Agno's ColoredRichHandler from stdout to stderr.
#
# Agno configures a Rich-based log handler that writes to sys.stdout by
# default.  Several tests parse structured SSE JSON from captured stdout
# (capsys.readouterr().out) and break when Agno's internal log_error()
# calls inject extra text into stdout (e.g. DB connection errors during
# the rag_retrieve step).  Redirecting to stderr keeps stdout clean.
try:
    from rich.console import Console

    from agno.utils.log import logger as _agno_logger

    for _handler in _agno_logger.handlers:
        if hasattr(_handler, "console"):
            _handler.console = Console(file=sys.stderr, highlight=False)
except Exception:
    pass
