"""Template version activation (harden-workflow-guardrails, design decision 10).

The declaration checks are unit tests.  The seeding scenarios write rows, so
they are marked ``destructive`` and run against the test database; they use a
key of their own and delete it afterwards.
"""

import os

import pytest
from sqlalchemy import create_engine, make_url, select
from sqlalchemy.orm import Session

from app.workflow.template_versions import apply_template_versions, check_active_versions

KEY = "test_template_versions_key"


def _definitions(*versions: int) -> list[dict]:
    return [{"template_key": KEY, "version": v, "template_text": f"text v{v}"} for v in versions]


# ---------------------------------------------------------------------------
# Declaration checks — no database
# ---------------------------------------------------------------------------


def test_valid_declaration_passes():
    check_active_versions(_definitions(1, 2), {KEY: 2})


def test_declared_version_not_defined_is_rejected():
    with pytest.raises(ValueError, match="v3 is not defined"):
        check_active_versions(_definitions(1, 2), {KEY: 3})


def test_defined_key_without_declaration_is_rejected():
    with pytest.raises(ValueError, match="no active version declared"):
        check_active_versions(_definitions(1), {})


def test_declared_key_not_defined_is_rejected():
    with pytest.raises(ValueError, match="'other' v1 is not defined"):
        check_active_versions(_definitions(1), {KEY: 1, "other": 1})


def test_seed_declaration_is_valid(monkeypatch):
    """The definitions and the active map in scripts/seed.py agree."""
    import importlib.util
    from pathlib import Path

    monkeypatch.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "unused"))
    path = Path(__file__).parent.parent / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_under_test", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)

    check_active_versions(seed.TEMPLATE_DEFINITIONS, seed.ACTIVE_TEMPLATE_VERSIONS)


# ---------------------------------------------------------------------------
# Seeding scenarios — write to the test database
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    url = os.environ["DATABASE_URL"]
    assert (make_url(url).database or "").endswith("_test_db"), "not a test database"
    engine = create_engine(url)
    with Session(engine) as s:
        yield s
    with Session(engine) as s:
        from sqlalchemy import delete

        from app.models.prompt_template import PromptTemplate

        s.execute(delete(PromptTemplate).where(PromptTemplate.template_key == KEY))
        s.commit()
    engine.dispose()


def _rows(session: Session) -> dict[int, bool]:
    from app.models.prompt_template import PromptTemplate

    session.expire_all()
    rows = session.execute(
        select(PromptTemplate.version, PromptTemplate.is_active).where(
            PromptTemplate.template_key == KEY
        )
    ).all()
    return dict(rows)


@pytest.mark.destructive
def test_fresh_key_activates_declared_version(session):
    apply_template_versions(session, _definitions(1, 2), {KEY: 2})
    assert _rows(session) == {1: False, 2: True}


@pytest.mark.destructive
def test_new_version_added_then_rolled_back(session):
    apply_template_versions(session, _definitions(1), {KEY: 1})
    assert _rows(session) == {1: True}

    apply_template_versions(session, _definitions(1, 2), {KEY: 2})
    assert _rows(session) == {1: False, 2: True}

    log = apply_template_versions(session, _definitions(1, 2), {KEY: 1})
    assert _rows(session) == {1: True, 2: False}
    assert not any(line.startswith("[insert]") for line in log)


@pytest.mark.destructive
def test_rerun_changes_nothing(session):
    apply_template_versions(session, _definitions(1, 2), {KEY: 2})
    assert apply_template_versions(session, _definitions(1, 2), {KEY: 2}) == []


@pytest.mark.destructive
def test_undefined_declared_version_leaves_database_unchanged(session):
    apply_template_versions(session, _definitions(1), {KEY: 1})
    with pytest.raises(ValueError):
        apply_template_versions(session, _definitions(1, 2), {KEY: 3})
    assert _rows(session) == {1: True}
