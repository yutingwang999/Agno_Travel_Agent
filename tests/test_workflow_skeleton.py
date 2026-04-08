"""
feat/workflow-skeleton merge checklist tests.

Verifies:
  - All 6 steps are importable from src/ without error
  - Running the workflow stub-to-stub produces one SSE event per step (6 total)
  - Every SSE event contains session_id, step, status, and timestamp

No DB or Docker required — skeleton steps are pure stubs.
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Module-level fixture: patch match_category for all skeleton tests.
#
# The skeleton tests are designed to run without a database.  Now that
# cag_match_executor has real logic, we patch match_category so tests remain
# independent of Docker / PostgreSQL / Gemini API.
# ---------------------------------------------------------------------------

_MOCK_MATCH_RESULT = None  # populated lazily to avoid import at module load


def _get_mock_match_result():
    global _MOCK_MATCH_RESULT
    if _MOCK_MATCH_RESULT is None:
        from app.workflow.cag_matcher import MatchResult

        _MOCK_MATCH_RESULT = MatchResult(
            category_key="family",
            confidence_score=0.85,
            tone="friendly and family-oriented",
            constraints="Activities must be suitable for children of all ages.",
            is_fallback=False,
        )
    return _MOCK_MATCH_RESULT


_VALID_ITINERARY_JSON = (
    '{"destination": "Sydney", "trip_length_days": 1, "budget_level": "moderate",'
    ' "travel_style": "family", "daily_itinerary": [{"day": 1, "morning": "Bondi Beach",'
    ' "afternoon": "Lunch", "evening": "Dinner", "estimated_cost_aud": 150.0}],'
    ' "total_estimated_cost_aud": 150.0, "key_tips": ["Book ahead"]}'
)


@pytest.fixture(autouse=True)
def patch_external_services(monkeypatch):
    """Patch all external service calls so skeleton tests run without a live DB or API."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.workflow.steps.cag_match.match_category",
        lambda **kwargs: _get_mock_match_result(),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: _VALID_ITINERARY_JSON,
    )
    # validate_output: patch DB and LLM so the step runs without a live connection.
    # The correction template and retry LLM are only reached when the first validation
    # fails (e.g. when no generate output is present in the step input).
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.resolve_template",
        lambda template_key, db_url, version=None: ("Fix this: {validation_errors}\n{raw_llm_output}", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output._call_llm",
        lambda prompt, api_key, model: _VALID_ITINERARY_JSON,
    )

# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_sse_utility_importable():
    from app.workflow.sse import build_sse_event, sse_event_to_json  # noqa: F401


def test_all_step_executors_importable():
    from app.workflow.steps import (  # noqa: F401
        cag_match_executor,
        generate_executor,
        intake_executor,
        rag_retrieve_executor,
        retrieval_decision_evaluator,
        validate_output_executor,
    )


def test_travel_workflow_importable():
    from app.workflow.travel_workflow import travel_workflow  # noqa: F401


def test_workflow_package_importable():
    from app.workflow import travel_workflow  # noqa: F401


# ---------------------------------------------------------------------------
# SSE utility unit tests
# ---------------------------------------------------------------------------


def test_build_sse_event_required_fields():
    from app.workflow.sse import build_sse_event

    event = build_sse_event(session_id="sid-1", step="intake", status="completed")

    assert event["session_id"] == "sid-1"
    assert event["step"] == "intake"
    assert event["status"] == "completed"
    assert "timestamp" in event
    assert "data" in event
    assert "error" in event


def test_build_sse_event_timestamp_is_iso8601():
    from app.workflow.sse import build_sse_event

    event = build_sse_event(session_id="sid-1", step="intake", status="completed")
    # Must parse without error
    datetime.fromisoformat(event["timestamp"])


def test_build_sse_event_default_data_is_empty_dict():
    from app.workflow.sse import build_sse_event

    event = build_sse_event(session_id="sid-1", step="intake", status="completed")
    assert event["data"] == {}


def test_build_sse_event_default_error_is_none():
    from app.workflow.sse import build_sse_event

    event = build_sse_event(session_id="sid-1", step="intake", status="completed")
    assert event["error"] is None


def test_build_sse_event_custom_data_and_error():
    from app.workflow.sse import build_sse_event

    event = build_sse_event(
        session_id="sid-1",
        step="validate_output",
        status="failed",
        data={"retry": True},
        error="schema mismatch",
    )
    assert event["data"] == {"retry": True}
    assert event["error"] == "schema mismatch"


def test_sse_event_to_json_is_valid_json():
    from app.workflow.sse import build_sse_event, sse_event_to_json

    event = build_sse_event(session_id="sid-1", step="generate", status="completed")
    raw = sse_event_to_json(event)
    parsed = json.loads(raw)
    assert parsed["step"] == "generate"


# ---------------------------------------------------------------------------
# Step executor unit tests (stubs, no DB)
# ---------------------------------------------------------------------------


def _make_step_input(session_id: str = "test-session"):
    from agno.workflow.types import StepInput

    return StepInput(
        input="plan a trip to Sydney",
        additional_data={
            "session_id": session_id,
            # Required fields for the intake step's TravelRequest validation.
            "destination": "Sydney",
            "trip_length": 5,
            "budget": "moderate",
            "travel_style": "family",
        },
    )


def _assert_sse_step_output(step_output, expected_step: str, session_id: str = "test-session"):
    """Parse StepOutput.content as SSE event and assert required fields."""
    assert step_output.content is not None
    event = json.loads(step_output.content)

    assert event["session_id"] == session_id, f"session_id mismatch in {expected_step}"
    assert event["step"] == expected_step, f"step name mismatch: {event['step']!r} != {expected_step!r}"
    assert event["status"] == "completed"
    assert "timestamp" in event
    datetime.fromisoformat(event["timestamp"])


def test_intake_executor_returns_sse_event():
    from app.workflow.steps.intake import intake_executor

    output = intake_executor(_make_step_input())
    _assert_sse_step_output(output, "intake")


def test_cag_match_executor_returns_sse_event():
    from app.workflow.steps.cag_match import cag_match_executor

    output = cag_match_executor(_make_step_input())
    _assert_sse_step_output(output, "cag_match")


def test_rag_retrieve_executor_returns_sse_event():
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    output = rag_retrieve_executor(_make_step_input())
    _assert_sse_step_output(output, "rag_retrieve")


def test_generate_executor_returns_sse_event():
    from app.workflow.steps.generate import generate_executor

    output = generate_executor(_make_step_input())
    _assert_sse_step_output(output, "generate")


def test_validate_output_executor_returns_sse_event():
    from app.workflow.steps.validate_output import validate_output_executor

    output = validate_output_executor(_make_step_input())
    _assert_sse_step_output(output, "validate_output")


def test_retrieval_decision_evaluator_returns_bool():
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input())
    assert isinstance(result, bool)


def test_retrieval_decision_evaluator_propagates_session_id(capsys):
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(session_id="sid-xyz"))
    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["session_id"] == "sid-xyz"
    assert event["step"] == "retrieval_decision"
    assert event["status"] == "completed"
    assert "timestamp" in event


# ---------------------------------------------------------------------------
# End-to-end workflow run: 6 SSE events, all required fields present
# ---------------------------------------------------------------------------


def _collect_sse_events(step_results) -> list[dict]:
    """Walk step_results (including nested Condition sub-steps) and collect SSE events.

    Skips any content that is not valid JSON — Agno inserts plain-text
    placeholder strings (e.g. "Condition … not met - skipped N steps") when
    a Condition branch is not taken.
    """
    events = []
    for step_result in step_results:
        if step_result.steps:
            # Condition node — the evaluator's event is not in step_results;
            # collect events from sub-steps (e.g. rag_retrieve) if they ran.
            for sub in step_result.steps:
                if sub.content:
                    try:
                        events.append(json.loads(sub.content))
                    except (json.JSONDecodeError, TypeError):
                        pass  # Agno placeholder string for a skipped branch
        elif step_result.content:
            try:
                events.append(json.loads(step_result.content))
            except (json.JSONDecodeError, TypeError):
                pass
    return events


def test_workflow_run_produces_six_sse_events(capsys):
    """All 6 steps emit one SSE event when the low-confidence path is taken."""
    from unittest.mock import patch

    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    # Use low confidence (<0.85) so rag_retrieve runs and all 6 events are emitted.
    low_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.50,
        tone="friendly and family-oriented",
        constraints="Activities must be suitable for children of all ages.",
        is_fallback=False,
    )

    session_id = "e2e-test-session"
    with patch("app.workflow.steps.cag_match.match_category", return_value=low_confidence_result):
        result = travel_workflow.run(
            input="plan a 5-day trip to Melbourne",
            additional_data={
                "session_id": session_id,
                "destination": "Melbourne",
                "trip_length": 5,
                "budget": "moderate",
                "travel_style": "family",
            },
        )

    # Events from step executors (intake, cag_match, rag_retrieve, generate, validate_output)
    executor_events = _collect_sse_events(result.step_results)

    # Event from retrieval_decision evaluator (printed as side-effect)
    captured = capsys.readouterr()
    evaluator_event = json.loads(captured.out.strip())

    all_events = executor_events + [evaluator_event]
    assert len(all_events) == 6, (
        f"Expected 6 SSE events, got {len(all_events)}: {[e['step'] for e in all_events]}"
    )


def test_workflow_run_all_events_have_required_fields(capsys):
    """Every SSE event must contain session_id, step, status, and timestamp."""
    from app.workflow.travel_workflow import travel_workflow

    session_id = "field-check-session"
    result = travel_workflow.run(
        input="plan a trip to Brisbane",
        additional_data={
            "session_id": session_id,
            "destination": "Brisbane",
            "trip_length": 3,
            "budget": "budget",
            "travel_style": "solo",
        },
    )

    executor_events = _collect_sse_events(result.step_results)
    captured = capsys.readouterr()
    evaluator_event = json.loads(captured.out.strip())
    all_events = executor_events + [evaluator_event]

    required_fields = {"session_id", "step", "status", "timestamp"}
    for event in all_events:
        missing = required_fields - event.keys()
        assert not missing, f"Event for step '{event.get('step')}' is missing fields: {missing}"


def test_workflow_run_session_id_propagated_to_all_events(capsys):
    """session_id must be identical in every SSE event."""
    from app.workflow.travel_workflow import travel_workflow

    session_id = "propagation-test-session"
    result = travel_workflow.run(
        input="plan a trip to Cairns",
        additional_data={
            "session_id": session_id,
            "destination": "Cairns",
            "trip_length": 4,
            "budget": "luxury",
            "travel_style": "romantic",
        },
    )

    executor_events = _collect_sse_events(result.step_results)
    captured = capsys.readouterr()
    evaluator_event = json.loads(captured.out.strip())
    all_events = executor_events + [evaluator_event]

    for event in all_events:
        assert event["session_id"] == session_id, (
            f"Step '{event['step']}' has wrong session_id: {event['session_id']!r}"
        )


def test_workflow_run_all_six_step_names_present(capsys):
    """All 6 step names appear in emitted events when low-confidence path is taken."""
    from unittest.mock import patch

    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    # Use low confidence so rag_retrieve runs and all 6 step names are present.
    low_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.50,
        tone="friendly and family-oriented",
        constraints="Activities must be suitable for children of all ages.",
        is_fallback=False,
    )

    with patch("app.workflow.steps.cag_match.match_category", return_value=low_confidence_result):
        result = travel_workflow.run(
            input="plan a trip to Perth",
            additional_data={
                "session_id": "step-name-test",
                "destination": "Perth",
                "trip_length": 7,
                "budget": "moderate",
                "travel_style": "adventure",
            },
        )

    executor_events = _collect_sse_events(result.step_results)
    captured = capsys.readouterr()
    evaluator_event = json.loads(captured.out.strip())
    all_events = executor_events + [evaluator_event]

    step_names = {e["step"] for e in all_events}
    expected = {"intake", "cag_match", "retrieval_decision", "rag_retrieve", "generate", "validate_output"}
    assert step_names == expected, f"Step name mismatch: {step_names} != {expected}"


def test_workflow_run_all_events_status_completed(capsys):
    """All stub events must have status='completed'."""
    from app.workflow.travel_workflow import travel_workflow

    result = travel_workflow.run(
        input="plan a trip to Darwin",
        additional_data={
            "session_id": "status-check-session",
            "destination": "Darwin",
            "trip_length": 6,
            "budget": "budget",
            "travel_style": "backpacker",
        },
    )

    executor_events = _collect_sse_events(result.step_results)
    captured = capsys.readouterr()
    evaluator_event = json.loads(captured.out.strip())
    all_events = executor_events + [evaluator_event]

    for event in all_events:
        assert event["status"] == "completed", (
            f"Step '{event['step']}' has status '{event['status']}', expected 'completed'"
        )
