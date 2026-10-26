"""
feat/db-schema merge checklist tests.

Static checks run as unit tests. Live-database checks are marked
`integration` (read-only) or `destructive` (alembic downgrade/upgrade) and run
against the test database (conftest.py points DATABASE_URL at
TEST_DATABASE_URL).

Requires for the live checks:
  - docker compose up (postgres running)
  - python scripts/dev.py test-db-setup

Run via:
  python scripts/dev.py verify-schema
"""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, make_url, text

MIGRATIONS_DIR = Path(__file__).parent.parent / "alembic" / "versions"

# Safety guard: destructive tests only ever run against a database whose name
# ends with this suffix, so a misconfigured URL cannot wipe the dev database.
TEST_DB_SUFFIX = "_test_db"


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


def _assert_test_database(url: str) -> None:
    name = make_url(url).database or ""
    assert name.endswith(TEST_DB_SUFFIX), (
        f"Refusing to run a destructive migration test against database {name!r}: "
        f"its name must end with {TEST_DB_SUFFIX!r}. Check TEST_DATABASE_URL in .env."
    )


# ---------------------------------------------------------------------------
# Static checks — no DB connection needed
# ---------------------------------------------------------------------------


def test_first_migration_enables_pgvector_extension():
    """CREATE EXTENSION IF NOT EXISTS vector must be in migration 0001."""
    migration_file = MIGRATIONS_DIR / "0001_enable_pgvector_create_itinerary_categories.py"
    assert migration_file.exists(), f"Migration file not found: {migration_file}"
    content = migration_file.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in content, (
        "Migration 0001 must contain: CREATE EXTENSION IF NOT EXISTS vector"
    )


def test_migration_chain_is_contiguous():
    """Revisions 0001-0005 must form an unbroken chain."""
    expected_chain = [
        ("0001", None),
        ("0002", "0001"),
        ("0003", "0002"),
        ("0004", "0003"),
        ("0005", "0004"),
    ]
    for revision, expected_down in expected_chain:
        files = list(MIGRATIONS_DIR.glob(f"{revision}_*.py"))
        assert len(files) == 1, f"Expected exactly one migration file for revision {revision}"
        content = files[0].read_text(encoding="utf-8")
        down_match = re.search(r'down_revision.*?=.*?"([^"]*)"', content)
        if expected_down is None:
            assert down_match is None or "None" in content, (
                f"Revision {revision} should have no parent"
            )
        else:
            assert down_match and down_match.group(1) == expected_down, (
                f"Revision {revision} should have down_revision={expected_down!r}"
            )


def test_models_import_without_error():
    """All 4 models and Base must be importable."""
    from app.models import (  # noqa: F401
        Base,
        ItineraryCategory,
        PromptTemplate,
        SourceDocument,
        TraceEvent,
    )


def test_itinerary_category_model_columns():
    """ItineraryCategory must have all columns defined in DESIGN.md section 5."""
    from app.models import ItineraryCategory

    column_names = {col.key for col in ItineraryCategory.__table__.columns}
    required = {"id", "category_key", "description", "tone", "constraints", "embedding_vector"}
    assert required == column_names, (
        f"ItineraryCategory columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(column_names)}"
    )


def test_prompt_template_model_columns():
    """PromptTemplate must have all columns defined in DESIGN.md section 5."""
    from app.models import PromptTemplate

    column_names = {col.key for col in PromptTemplate.__table__.columns}
    required = {"id", "template_key", "version", "template_text", "is_active", "created_at"}
    assert required == column_names, (
        f"PromptTemplate columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(column_names)}"
    )


def test_source_document_model_columns():
    """SourceDocument must have all columns defined in DESIGN.md section 5."""
    from app.models import SourceDocument

    column_names = {col.key for col in SourceDocument.__table__.columns}
    required = {"id", "destination", "title", "chunk_text", "embedding_vector", "metadata_json"}
    assert required == column_names, (
        f"SourceDocument columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(column_names)}"
    )


def test_trace_event_model_columns():
    """TraceEvent must have all columns defined in DESIGN.md section 5."""
    from app.models import TraceEvent

    column_names = {col.key for col in TraceEvent.__table__.columns}
    required = {
        "id", "session_id", "step_name", "status", "latency_ms",
        "prompt_template_key", "prompt_template_version",
        "error_type", "degraded_mode", "created_at",
        "input_tokens", "output_tokens",
    }
    assert required == column_names, (
        f"TraceEvent columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(column_names)}"
    )


# ---------------------------------------------------------------------------
# Integration checks — require running Postgres with migrations applied
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(_database_url())
    yield engine
    engine.dispose()


@pytest.mark.integration
def test_pgvector_extension_is_active(db_engine):
    """The vector extension must be present in the live database."""
    with db_engine.connect() as conn:
        result = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        row = result.fetchone()
    assert row is not None, "pgvector extension is not installed in the database"


@pytest.mark.integration
def test_all_four_tables_exist(db_engine):
    """All 4 tables must exist after alembic upgrade head."""
    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = {
        "itinerary_categories",
        "prompt_templates",
        "source_documents",
        "trace_events",
    }
    missing = expected_tables - existing_tables
    assert not missing, f"Missing tables after upgrade head: {missing}"


@pytest.mark.integration
def test_itinerary_categories_db_columns(db_engine):
    """Live itinerary_categories columns must match DESIGN.md section 5."""
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("itinerary_categories")}
    required = {"id", "category_key", "description", "tone", "constraints", "embedding_vector"}
    assert required == columns, (
        f"itinerary_categories DB columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(columns)}"
    )


@pytest.mark.integration
def test_prompt_templates_db_columns(db_engine):
    """Live prompt_templates columns must match DESIGN.md section 5."""
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("prompt_templates")}
    required = {"id", "template_key", "version", "template_text", "is_active", "created_at"}
    assert required == columns, (
        f"prompt_templates DB columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(columns)}"
    )


@pytest.mark.integration
def test_source_documents_db_columns(db_engine):
    """Live source_documents columns must match DESIGN.md section 5."""
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("source_documents")}
    required = {"id", "destination", "title", "chunk_text", "embedding_vector", "metadata_json"}
    assert required == columns, (
        f"source_documents DB columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(columns)}"
    )


@pytest.mark.integration
def test_trace_events_db_columns(db_engine):
    """Live trace_events columns must match DESIGN.md section 5."""
    inspector = inspect(db_engine)
    columns = {col["name"] for col in inspector.get_columns("trace_events")}
    required = {
        "id", "session_id", "step_name", "status", "latency_ms",
        "prompt_template_key", "prompt_template_version",
        "error_type", "degraded_mode", "created_at",
        "input_tokens", "output_tokens",
    }
    assert required == columns, (
        f"trace_events DB columns mismatch.\nExpected: {sorted(required)}\nGot: {sorted(columns)}"
    )


@pytest.mark.integration
def test_trace_events_has_session_id_index(db_engine):
    """trace_events must have an index on session_id for query performance."""
    inspector = inspect(db_engine)
    indexes = inspector.get_indexes("trace_events")
    indexed_columns = {col for idx in indexes for col in idx["column_names"]}
    assert "session_id" in indexed_columns, (
        "trace_events is missing an index on session_id"
    )


@pytest.mark.destructive
def test_downgrade_removes_all_tables(db_engine):
    """alembic downgrade base must remove all 4 tables and the vector extension."""
    import subprocess
    import sys

    database_url = _database_url()
    _assert_test_database(database_url)

    project_root = str(Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic downgrade base failed:\n{result.stderr}"

    inspector = inspect(db_engine)
    # Refresh connection after DDL
    db_engine.dispose()
    from sqlalchemy import create_engine as _ce
    fresh_engine = _ce(database_url)
    inspector = inspect(fresh_engine)
    remaining = set(inspector.get_table_names()) & {
        "itinerary_categories", "prompt_templates", "source_documents", "trace_events"
    }
    fresh_engine.dispose()
    assert not remaining, f"Tables still exist after downgrade base: {remaining}"


@pytest.mark.destructive
def test_upgrade_head_reapplies_cleanly(db_engine):
    """alembic upgrade head must succeed after a full downgrade."""
    import subprocess
    import sys

    project_root = str(Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade head failed after downgrade:\n{result.stderr}"

    from sqlalchemy import create_engine as _ce
    fresh_engine = _ce(_database_url())
    inspector = inspect(fresh_engine)
    existing = set(inspector.get_table_names())
    fresh_engine.dispose()

    expected = {"itinerary_categories", "prompt_templates", "source_documents", "trace_events"}
    missing = expected - existing
    assert not missing, f"Tables missing after re-upgrade: {missing}"
