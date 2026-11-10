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


GENERATION_KEYS = ("high_confidence_minimal_context", "low_confidence_with_retrieval", "itinerary_with_context")
V010_KEYS = ("high_confidence_minimal_context", "low_confidence_with_retrieval", "validate_output_correction")


def test_seed_active_generation_templates_state_the_ceiling(seed_module):
    """Every active generation template carries the {daily_budget_ceiling} placeholder."""
    for d in _active_definitions(seed_module):
        if d["template_key"] in GENERATION_KEYS:
            assert "{daily_budget_ceiling}" in d["template_text"], d["template_key"]


def test_seed_v1_templates_are_unchanged(seed_module):
    """Version 1 of the v0.1.0 keys keeps the v0.1.0 text, so the baseline stays reproducible."""
    v1 = {d["template_key"]: d["template_text"] for d in seed_module.TEMPLATE_DEFINITIONS
          if d["version"] == 1 and d["template_key"] in V010_KEYS}
    assert set(v1) == set(V010_KEYS)
    for text in v1.values():
        assert COST_UNIT_PHRASE not in text


def _itinerary_with_context(seed) -> dict[int, str]:
    return {d["version"]: d["template_text"] for d in seed.TEMPLATE_DEFINITIONS
            if d["template_key"] == "itinerary_with_context"}


def test_itinerary_with_context_versions_carry_every_required_part(seed_module):
    """Spec "Single generation template": every variant has the knowledge context and the notes,
    harden's cost unit and ceiling, citation instructions, and a JSON example with single braces.
    v5 is the task 5.6 diagnosis without the cost unit and ceiling; it is never active."""
    versions = _itinerary_with_context(seed_module)
    assert set(versions) == {1, 2, 3, 4, 5}
    assert seed_module.ACTIVE_TEMPLATE_VERSIONS["itinerary_with_context"] != 5
    for version, text in versions.items():
        parts = ["{retrieved_context}", "{notes}", '"sources"', "[S1]"]
        if version != 5:
            parts += ["{daily_budget_ceiling}", COST_UNIT_PHRASE]
        for part in parts:
            assert part in text, (version, part)
        assert "{{" not in text and "}}" not in text, version


def test_itinerary_with_context_v5_is_v4_without_the_budget_sentences(seed_module):
    """Task 5.6: v5 removes exactly harden's cost-unit and ceiling sentences from v4."""
    versions = _itinerary_with_context(seed_module)
    v4, v5 = versions[4], versions[5]
    assert COST_UNIT_PHRASE not in v5 and "{daily_budget_ceiling}" not in v5
    restored = v5.replace("\n\nUse the following reference information",
                          f"\n{seed_module.COST_UNIT_SENTENCE}\n{seed_module.BUDGET_CEILING_SENTENCE}"
                          "\n\nUse the following reference information")
    assert restored == v4


def test_itinerary_with_context_variants_differ_only_in_the_request_description(seed_module):
    """Design decision 3: A has the preset, B the traveller's own style, C both."""
    a, b, c = (_itinerary_with_context(seed_module)[v] for v in (1, 2, 3))
    assert "{matched_category}" in a and "{travel_style}" not in a
    assert "{travel_style}" in b and "{matched_category}" not in b and "{constraints}" not in b
    assert "{travel_style}" in c and "{matched_category}" in c and "{constraints}" in c
    tail = a[a.index("All costs are"):]
    assert b.endswith(tail) and c.endswith(tail)


def test_itinerary_with_context_v4_is_c_plus_one_instruction(seed_module):
    """Design decision 4 (task 5.5): v4 changes one thing against the 5.4 winner."""
    versions = _itinerary_with_context(seed_module)
    sentence = seed_module.NO_INVENTED_EXCLUSIVES_SENTENCE
    assert sentence not in versions[3]
    assert versions[4] == versions[3].replace(
        "Return ONLY a valid JSON object", f"{sentence}\n\nReturn ONLY a valid JSON object")


def test_correction_v3_keeps_citations_and_has_single_braces(seed_module):
    text = next(d["template_text"] for d in seed_module.TEMPLATE_DEFINITIONS
                if d["template_key"] == "validate_output_correction" and d["version"] == 3)
    assert seed_module.ACTIVE_TEMPLATE_VERSIONS["validate_output_correction"] == 3
    assert '"sources": [string]' in text and "citation" in text
    assert "{validation_errors}" in text and "{raw_llm_output}" in text
    assert "{{" not in text and "}}" not in text


def test_itinerary_with_context_v4_is_active(seed_module):
    """Variant C won task 5.4; v4 (C without invented exclusives) was adopted in task 5.5."""
    assert seed_module.ACTIVE_TEMPLATE_VERSIONS["itinerary_with_context"] == 4


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


@pytest.mark.integration
def test_seeded_active_generation_templates_state_the_ceiling():
    """After test-db-setup, every active generation template has {daily_budget_ceiling}."""
    from app.models.prompt_template import PromptTemplate

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(engine) as s:
            rows = s.execute(
                select(PromptTemplate.template_key, PromptTemplate.template_text).where(
                    PromptTemplate.is_active, PromptTemplate.template_key.in_(GENERATION_KEYS)
                )
            ).all()
    finally:
        engine.dispose()
    assert len(rows) == len(GENERATION_KEYS), "run test-db-setup"
    for key, text in rows:
        assert "{daily_budget_ceiling}" in text, key
