"""feat/cag-match merge checklist tests.

Verifies:
  - matched_category and confidence_score are present in workflow state (SSE
    event data) after step 2
  - A request that matches no category still completes step 2 with a fallback
    category (no unhandled exception)
  - Embedding model used in cag_match is the same model used in seed.py
    (gemini-embedding-001, 768 dimensions)
  - cag_match_executor produces a valid SSE event with the required structure

Most tests mock match_category so no database or API key is required.
Integration tests (marked with pytest.mark.integration) require a live
PostgreSQL + pgvector database and a valid GEMINI_API_KEY.
"""

import json
import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ADDITIONAL_DATA = {
    "session_id": "cag-test-session",
    "destination": "sydney",
    "trip_length": 5,
    "budget": "moderate",
    "travel_style": "family",
}


def _make_step_input(overrides: dict | None = None):
    from agno.workflow.types import StepInput

    additional_data = {**VALID_ADDITIONAL_DATA, **(overrides or {})}
    return StepInput(
        input="plan a trip",
        additional_data=additional_data,
    )


def _make_match_result(
    category_key: str = "family",
    confidence_score: float = 0.85,
    tone: str = "friendly and family-oriented",
    constraints: str = "Activities must be suitable for children of all ages.",
    is_fallback: bool = False,
):
    from app.workflow.cag_matcher import MatchResult

    return MatchResult(
        category_key=category_key,
        confidence_score=confidence_score,
        tone=tone,
        constraints=constraints,
        is_fallback=is_fallback,
    )


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_cag_matcher_module_importable():
    from app.workflow.cag_matcher import MatchResult, match_category  # noqa: F401


def test_cag_match_executor_importable():
    from app.workflow.steps.cag_match import cag_match_executor  # noqa: F401


# ---------------------------------------------------------------------------
# MatchResult dataclass
# ---------------------------------------------------------------------------


def test_match_result_fields():
    result = _make_match_result()
    assert result.category_key == "family"
    assert result.confidence_score == 0.85
    assert result.tone == "friendly and family-oriented"
    assert result.constraints == "Activities must be suitable for children of all ages."
    assert result.is_fallback is False


def test_match_result_fallback_flag():
    result = _make_match_result(is_fallback=True, confidence_score=0.10)
    assert result.is_fallback is True
    assert result.confidence_score == 0.10


# ---------------------------------------------------------------------------
# cag_match_executor — SSE output structure (mocked match_category)
# ---------------------------------------------------------------------------


def test_cag_match_executor_returns_valid_sse_event(monkeypatch):
    """Checklist: matched_category and confidence_score present in SSE data."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _make_match_result(category_key="family", confidence_score=0.88)

    with patch("app.workflow.steps.cag_match.match_category", return_value=mock_result):
        from app.workflow.steps.cag_match import cag_match_executor

        output = cag_match_executor(_make_step_input())

    assert output.content is not None
    event = json.loads(output.content)

    assert event["step"] == "cag_match"
    assert event["status"] == "completed"
    assert event["session_id"] == "cag-test-session"
    assert "timestamp" in event


def test_cag_match_executor_data_contains_matched_category(monkeypatch):
    """Checklist: matched_category present in workflow state after step 2."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _make_match_result(category_key="adventure", confidence_score=0.91)

    with patch("app.workflow.steps.cag_match.match_category", return_value=mock_result):
        from app.workflow.steps.cag_match import cag_match_executor

        output = cag_match_executor(_make_step_input())

    data = json.loads(output.content)["data"]

    assert "matched_category" in data
    assert data["matched_category"] == "adventure"


def test_cag_match_executor_data_contains_confidence_score(monkeypatch):
    """Checklist: confidence_score present in workflow state after step 2."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _make_match_result(confidence_score=0.79)

    with patch("app.workflow.steps.cag_match.match_category", return_value=mock_result):
        from app.workflow.steps.cag_match import cag_match_executor

        output = cag_match_executor(_make_step_input())

    data = json.loads(output.content)["data"]

    assert "confidence_score" in data
    assert data["confidence_score"] == pytest.approx(0.79)


def test_cag_match_executor_data_contains_tone_and_constraints(monkeypatch):
    """tone and constraints must be present for downstream generate step."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _make_match_result(
        tone="practical and cost-conscious",
        constraints="Prioritise free or low-cost activities.",
    )

    with patch("app.workflow.steps.cag_match.match_category", return_value=mock_result):
        from app.workflow.steps.cag_match import cag_match_executor

        output = cag_match_executor(_make_step_input())

    data = json.loads(output.content)["data"]

    assert data["tone"] == "practical and cost-conscious"
    assert data["constraints"] == "Prioritise free or low-cost activities."


# ---------------------------------------------------------------------------
# Fallback behaviour — checklist: no unhandled exception when no match found
# ---------------------------------------------------------------------------


def test_cag_match_executor_completes_with_fallback_category(monkeypatch):
    """Checklist: request matching no category still completes with a fallback."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    # Simulate a very low confidence score — below MINIMUM_SIMILARITY
    fallback_result = _make_match_result(
        category_key="family",
        confidence_score=0.12,
        is_fallback=True,
    )

    with patch("app.workflow.steps.cag_match.match_category", return_value=fallback_result):
        from app.workflow.steps.cag_match import cag_match_executor

        # Must not raise — checklist requirement
        output = cag_match_executor(_make_step_input())

    event = json.loads(output.content)
    data = event["data"]

    assert event["status"] == "completed"
    assert data["matched_category"] == "family"
    assert data["is_fallback"] is True
    assert data["confidence_score"] == pytest.approx(0.12)


def test_cag_match_executor_no_exception_on_zero_confidence(monkeypatch):
    """Step 2 must not raise even when confidence_score is 0.0 (no DB rows)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    zero_confidence_result = _make_match_result(
        category_key="family",
        confidence_score=0.0,
        tone="friendly and helpful",
        constraints="",
        is_fallback=True,
    )

    with patch("app.workflow.steps.cag_match.match_category", return_value=zero_confidence_result):
        from app.workflow.steps.cag_match import cag_match_executor

        output = cag_match_executor(_make_step_input())

    assert json.loads(output.content)["status"] == "completed"


# ---------------------------------------------------------------------------
# Embedding model consistency — checklist requirement
# ---------------------------------------------------------------------------


def test_cag_matcher_uses_same_embedding_model_as_seed():
    """Checklist: embedding model in cag_match must match seed.py (gemini-embedding-001)."""
    import inspect

    import app.workflow.cag_matcher as matcher_module
    import scripts.seed as seed_module  # noqa: PLC0415

    # Both modules must reference the same default model name
    matcher_source = inspect.getsource(matcher_module)
    seed_source = inspect.getsource(seed_module)

    assert "gemini-embedding-001" in matcher_source, (
        "cag_matcher.py must reference gemini-embedding-001 as the default embedding model"
    )
    assert "gemini-embedding-001" in seed_source, (
        "seed.py must reference gemini-embedding-001 as the embedding model"
    )


def test_cag_matcher_default_embedding_model_is_gemini_embedding_001():
    """match_category default embedding_model parameter must be gemini-embedding-001."""
    import inspect

    from app.workflow.cag_matcher import match_category

    sig = inspect.signature(match_category)
    default_model = sig.parameters["embedding_model"].default
    assert default_model == "gemini-embedding-001", (
        f"Expected default embedding_model='gemini-embedding-001', got {default_model!r}"
    )


def test_cag_matcher_embedding_dimensions_match_seed():
    """Both cag_matcher and itinerary_category model must use 768 dimensions."""
    from app.models.itinerary_category import EMBEDDING_DIMENSIONS as model_dims
    from app.workflow.cag_matcher import EMBEDDING_DIMENSIONS as matcher_dims

    assert matcher_dims == 768
    assert model_dims == 768
    assert matcher_dims == model_dims


# ---------------------------------------------------------------------------
# Integration tests — require live PostgreSQL + Gemini API
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_match_category_returns_result_with_seeded_db():
    """Integration: match_category returns a valid MatchResult against seeded DB."""
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not db_url or not api_key:
        pytest.skip("DATABASE_URL and GEMINI_API_KEY required for integration tests")

    from app.workflow.cag_matcher import MatchResult, match_category

    result = match_category(
        intent_text="family trip to Sydney with moderate budget",
        db_url=db_url,
        api_key=api_key,
    )

    assert isinstance(result, MatchResult)
    assert result.category_key  # non-empty string
    assert 0.0 <= result.confidence_score <= 1.0
    assert result.tone
    assert isinstance(result.is_fallback, bool)


@pytest.mark.integration
def test_cag_match_executor_integration():
    """Integration: cag_match_executor returns matched_category and confidence_score."""
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not db_url or not api_key:
        pytest.skip("DATABASE_URL and GEMINI_API_KEY required for integration tests")

    from agno.workflow.types import StepInput

    from app.workflow.steps.cag_match import cag_match_executor

    step_input = StepInput(
        input="plan a trip",
        additional_data={
            "session_id": "integration-test",
            "destination": "sydney",
            "trip_length": 5,
            "budget": "moderate",
            "travel_style": "family",
        },
    )

    output = cag_match_executor(step_input)
    event = json.loads(output.content)
    data = event["data"]

    # Checklist: both fields must be present
    assert "matched_category" in data
    assert "confidence_score" in data
    assert event["step"] == "cag_match"
    assert event["status"] == "completed"


@pytest.mark.integration
def test_match_category_fallback_when_below_threshold():
    """Integration: low-similarity intent still returns a result without raising."""
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not db_url or not api_key:
        pytest.skip("DATABASE_URL and GEMINI_API_KEY required for integration tests")

    from app.workflow.cag_matcher import match_category

    # Gibberish text is unlikely to exceed any reasonable similarity threshold
    result = match_category(
        intent_text="xyzzy frobnicator glorp",
        db_url=db_url,
        api_key=api_key,
    )

    # Must complete without exception — checklist requirement
    assert result.category_key  # fallback category key is set
    assert 0.0 <= result.confidence_score <= 1.0
