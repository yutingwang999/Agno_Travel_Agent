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


COST_UNIT_PHRASE = "AUD per person, excluding accommodation"


@pytest.fixture(scope="module")
def seed_module():
    """scripts/seed.py loaded as a module (it reads GEMINI_API_KEY at import)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_under_test", path)
    seed = importlib.util.module_from_spec(spec)
    # Only for the import: conftest decides from GEMINI_API_KEY whether
    # integration tests can run, so a placeholder must not outlive this fixture.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "unused"))
        spec.loader.exec_module(seed)
    return seed


def _active_definitions(seed) -> list[dict]:
    return [
        d
        for d in seed.TEMPLATE_DEFINITIONS
        if seed.ACTIVE_TEMPLATE_VERSIONS[d["template_key"]] == d["version"]
    ]


def test_seed_declaration_is_valid(seed_module):
    """The definitions and the active map in scripts/seed.py agree."""
    check_active_versions(seed_module.TEMPLATE_DEFINITIONS, seed_module.ACTIVE_TEMPLATE_VERSIONS)


def test_seed_active_templates_state_the_cost_unit(seed_module):
    """Every template seed activates states the cost unit."""
    active = _active_definitions(seed_module)
    assert len(active) == len(seed_module.ACTIVE_TEMPLATE_VERSIONS)
    for d in active:
        assert COST_UNIT_PHRASE in d["template_text"], d["template_key"]


def test_seed_v1_templates_are_unchanged(seed_module):
    """Version 1 keeps the v0.1.0 text, so the baseline stays reproducible."""
    v1 = {d["template_key"]: d["template_text"] for d in seed_module.TEMPLATE_DEFINITIONS if d["version"] == 1}
    for text in v1.values():
        assert COST_UNIT_PHRASE not in text


@pytest.mark.integration
def test_seeded_active_templates_state_the_cost_unit():
    """After test-db-setup, every active template in the database states the cost unit."""
    from app.models.prompt_template import PromptTemplate

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(engine) as s:
            rows = s.execute(
                select(PromptTemplate.template_key, PromptTemplate.template_text).where(
                    PromptTemplate.is_active
                )
            ).all()
    finally:
        engine.dispose()
    assert rows, "no active templates; run test-db-setup"
    for key, text in rows:
        assert COST_UNIT_PHRASE in text, key


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
