"""Golden tests for feat/testing branch.

Three golden tests validating structure and branch correctness:
  1. Family trip request → high-confidence path, no RAG, structured itinerary returned
  2. Budget trip request → high-confidence path, no RAG, structured itinerary returned
  3. Low-confidence request → RAG path taken, rag_retrieve SSE event present in stream

These are integration tests requiring a live PostgreSQL database and Gemini API key.
They assert structure and branch correctness — NOT exact LLM output strings.

Run with: pytest -m integration tests/test_golden.py
"""

import contextlib
import io
import json
import uuid
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Required top-level fields in the itinerary output schema (DESIGN.md section 6)
ITINERARY_REQUIRED_FIELDS = {
    "destination",
    "trip_length_days",
    "budget_level",
    "travel_style",
    "daily_itinerary",
    "total_estimated_cost_aud",
    "key_tips",
}

# Required fields in every SSE event (DESIGN.md section 9)
SSE_REQUIRED_FIELDS = {"session_id", "step", "status", "timestamp", "data", "error"}


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _run_workflow_and_collect_events(
    session_id: str,
    destination: str,
    trip_length: int,
    budget: str,
    travel_style: str,
    confidence_score: float,
    is_fallback: bool = False,
) -> list[dict]:
    """Run the travel workflow with a mocked CAG matcher and return all SSE events.

    The CAG matcher is patched to return a fixed confidence_score so that
    branching is deterministic — high confidence skips RAG, low confidence
    triggers it.

    Args:
        session_id:       Unique identifier for the test run.
        destination:      Travel destination (lowercased).
        trip_length:      Number of days.
        budget:           Budget level string.
        travel_style:     Travel style string.
        confidence_score: Mocked CAG confidence score controlling branch path.
        is_fallback:      Whether the CAG matcher fell back to a default category
                          because no match exceeded minimum similarity.

    Returns:
        List of parsed SSE event dicts emitted by the workflow.
    """
    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    mock_result = MatchResult(
        category_key="general" if is_fallback else "weekend",
        confidence_score=confidence_score,
        tone="friendly",
        constraints="suitable for all",
        is_fallback=is_fallback,
    )

    with patch(
        "app.workflow.steps.cag_match.match_category",
        return_value=mock_result,
    ):
        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            result = travel_workflow.run(
                input=f"plan a {trip_length}-day trip to {destination}",
                additional_data={
                    "session_id": session_id,
                    "destination": destination,
                    "trip_length": trip_length,
                    "budget": budget,
                    "travel_style": travel_style,
                },
            )

    # Collect events from step results (mirrors _collect_step_result_events in main.py)
    events: list[dict] = []
    for step_result in result.step_results:
        if step_result.steps:
            # Condition node — recurse into sub-steps (e.g. rag_retrieve)
            for sub in step_result.steps:
                if sub.content:
                    try:
                        events.append(json.loads(sub.content))
                    except (json.JSONDecodeError, TypeError):
                        pass
        elif step_result.content:
            try:
                events.append(json.loads(step_result.content))
            except (json.JSONDecodeError, TypeError):
                pass

    # Parse the retrieval_decision event emitted to stdout
    stdout_text = captured_stdout.getvalue().strip()
    if stdout_text:
        for line in stdout_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if isinstance(event, dict) and "step" in event:
                    events.append(event)
            except (json.JSONDecodeError, TypeError):
                pass

    return events


def _assert_sse_structure(events: list[dict]) -> None:
    """Assert every event has the required SSE fields."""
    assert events, "Expected at least one SSE event but got none"
    for event in events:
        missing = SSE_REQUIRED_FIELDS - event.keys()
        assert not missing, (
            f"Event for step '{event.get('step')}' is missing fields: {missing}"
        )


def _get_itinerary(events: list[dict]) -> dict:
    """Extract and return the itinerary dict from the validate_output event."""
    validate_event = next(
        (e for e in events if e.get("step") == "validate_output"), None
    )
    assert validate_event is not None, (
        f"No validate_output event found in steps: {[e.get('step') for e in events]}"
    )
    itinerary = validate_event.get("data", {}).get("itinerary", {})
    assert itinerary, "validate_output data.itinerary is empty or missing"
    return itinerary


# ---------------------------------------------------------------------------
# Golden test 1: family trip — high-confidence path, no RAG
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_golden_family_trip_high_confidence_no_rag():
    """Golden test 1: family trip → high-confidence path, no RAG, structured itinerary.

    Asserts:
    - rag_retrieve event is NOT present (high-confidence branch taken)
    - All required workflow steps are present in the SSE stream
    - Every SSE event has the required fields
    - validate_output data.itinerary contains all required schema fields
    """
    session_id = f"golden-family-{uuid.uuid4()}"
    events = _run_workflow_and_collect_events(
        session_id=session_id,
        destination="sydney",
        trip_length=5,
        budget="moderate",
        travel_style="family",
        confidence_score=0.90,  # above threshold → skip RAG
    )

    step_names = [e.get("step") for e in events]

    # Branch correctness: rag_retrieve must NOT appear
    assert "rag_retrieve" not in step_names, (
        f"Expected no rag_retrieve for high-confidence path, got: {step_names}"
    )

    # Required steps must all be present
    for required_step in (
        "intake", "cag_match", "retrieval_decision", "generate", "validate_output"
    ):
        assert required_step in step_names, (
            f"Expected step '{required_step}' in events, got: {step_names}"
        )

    # All events must have the required SSE fields
    _assert_sse_structure(events)

    # validate_output must contain a structured itinerary with all required fields
    itinerary = _get_itinerary(events)
    missing_fields = ITINERARY_REQUIRED_FIELDS - itinerary.keys()
    assert not missing_fields, f"Itinerary missing required fields: {missing_fields}"


# ---------------------------------------------------------------------------
# Golden test 2: budget trip — high-confidence path, no RAG
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_golden_budget_trip_high_confidence_no_rag():
    """Golden test 2: budget trip → high-confidence path, no RAG, structured itinerary.

    Same branch as golden test 1 but with a budget travel style and Melbourne
    as the destination.

    Asserts:
    - rag_retrieve event is NOT present (high-confidence branch taken)
    - All required workflow steps are present in the SSE stream
    - Every SSE event has the required fields
    - validate_output data.itinerary contains all required schema fields
    """
    session_id = f"golden-budget-{uuid.uuid4()}"
    events = _run_workflow_and_collect_events(
        session_id=session_id,
        destination="melbourne",
        trip_length=3,
        budget="budget",
        travel_style="budget",
        confidence_score=0.85,  # above threshold → skip RAG
    )

    step_names = [e.get("step") for e in events]

    # Branch correctness: rag_retrieve must NOT appear
    assert "rag_retrieve" not in step_names, (
        f"Expected no rag_retrieve for high-confidence path, got: {step_names}"
    )

    # Required steps must all be present
    for required_step in (
        "intake", "cag_match", "retrieval_decision", "generate", "validate_output"
    ):
        assert required_step in step_names, (
            f"Expected step '{required_step}' in events, got: {step_names}"
        )

    # All events must have the required SSE fields
    _assert_sse_structure(events)

    # validate_output must contain a structured itinerary with all required fields
    itinerary = _get_itinerary(events)
    missing_fields = ITINERARY_REQUIRED_FIELDS - itinerary.keys()
    assert not missing_fields, f"Itinerary missing required fields: {missing_fields}"


# ---------------------------------------------------------------------------
# Golden test 3: low-confidence request — RAG path taken
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_golden_low_confidence_rag_path_taken():
    """Golden test 3: low-confidence request → RAG path, rag_retrieve event present,
    retrieved context injected into the itinerary response.

    Asserts:
    - rag_retrieve event IS present (low-confidence branch taken)
    - retrieval_decision routing_decision is 'rag_retrieve'
    - rag_retrieve data.retrieved_context is a non-empty list (context was injected)
    - All required workflow steps (including rag_retrieve) are present
    - Every SSE event has the required fields
    - validate_output data.itinerary contains all required schema fields
    """
    session_id = f"golden-lowconf-{uuid.uuid4()}"
    events = _run_workflow_and_collect_events(
        session_id=session_id,
        # A real Australian place, so the destination guard accepts it through the API;
        # with this unusual style the real CAG match is 0.836 (measured 2026-10-31,
        # gemini-embedding-001), below the 0.85 threshold. The test mocks the score.
        destination="alice springs",
        trip_length=4,
        budget="moderate",
        travel_style="spontaneous_urban_nomad",  # unusual style → low-confidence match
        confidence_score=0.50,  # below 0.85 threshold → trigger RAG
        is_fallback=False,  # a category was matched, just not confidently enough to skip RAG
    )

    step_names = [e.get("step") for e in events]

    # Branch correctness: rag_retrieve MUST appear
    assert "rag_retrieve" in step_names, (
        f"Expected rag_retrieve for low-confidence path, got: {step_names}"
    )

    # All required steps including rag_retrieve must be present
    for required_step in (
        "intake", "cag_match", "retrieval_decision", "rag_retrieve",
        "generate", "validate_output"
    ):
        assert required_step in step_names, (
            f"Expected step '{required_step}' in events, got: {step_names}"
        )

    # All events must have the required SSE fields
    _assert_sse_structure(events)

    # retrieval_decision must route to rag_retrieve
    rd_event = next(
        (e for e in events if e.get("step") == "retrieval_decision"), None
    )
    assert rd_event is not None, "No retrieval_decision event found"
    routing_decision = rd_event.get("data", {}).get("routing_decision")
    assert routing_decision == "rag_retrieve", (
        f"Expected routing_decision='rag_retrieve', got: {routing_decision!r}"
    )

    # rag_retrieve must have retrieved at least one chunk (context was injected)
    rag_event = next(
        (e for e in events if e.get("step") == "rag_retrieve"), None
    )
    assert rag_event is not None, "No rag_retrieve event found"
    retrieved_context = rag_event.get("data", {}).get("retrieved_context")
    assert isinstance(retrieved_context, list) and len(retrieved_context) > 0, (
        f"Expected non-empty retrieved_context in rag_retrieve event, "
        f"got: {retrieved_context!r}"
    )

    # validate_output must contain a structured itinerary with all required fields
    itinerary = _get_itinerary(events)
    missing_fields = ITINERARY_REQUIRED_FIELDS - itinerary.keys()
    assert not missing_fields, f"Itinerary missing required fields: {missing_fields}"


# ---------------------------------------------------------------------------
# End-to-end test: POST /generate → SSE stream contains all 6 step events
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_e2e_post_generate_sse_stream_contains_all_six_step_events():
    """End-to-end test: POST /generate → full SSE stream with all 6 step events.

    Makes a real HTTP call to the FastAPI app (no mocking of _run_workflow or
    the workflow steps) and verifies that the SSE stream contains exactly the
    expected step events for a low-confidence path (all 6 steps present).

    Asserts:
    - Response is 200 with Content-Type: text/event-stream
    - All 6 step names appear in the SSE stream
    - Every event has the required SSE fields (session_id, step, status,
      timestamp, data, error)
    - session_id is consistent across all events
    """
    from fastapi.testclient import TestClient
    from sse_starlette.sse import AppStatus

    from app.main import app
    from app.workflow.cag_matcher import MatchResult

    # Reset sse-starlette AppStatus so there is no stale event loop binding
    AppStatus.should_exit_event = None

    low_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.50,
        tone="friendly",
        constraints="child-friendly",
        is_fallback=False,
    )

    request_body = {
        "destination": "Sydney",
        "trip_length": 3,
        "budget": "moderate",
        "travel_style": "family",
    }

    with patch(
        "app.workflow.steps.cag_match.match_category",
        return_value=low_confidence_result,
    ):
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post("/generate", json=request_body)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Parse every `data: ...` line from the raw SSE body
    events = []
    for line in response.text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[len("data: "):]))
            except (json.JSONDecodeError, TypeError):
                pass

    step_names = [e.get("step") for e in events]

    # All 6 steps must be present (low-confidence path includes rag_retrieve)
    for required_step in (
        "intake", "cag_match", "retrieval_decision", "rag_retrieve",
        "generate", "validate_output"
    ):
        assert required_step in step_names, (
            f"Expected step '{required_step}' in SSE stream, got: {step_names}"
        )

    # Every event must have the required SSE fields
    for event in events:
        missing = SSE_REQUIRED_FIELDS - event.keys()
        assert not missing, (
            f"Event for step '{event.get('step')}' is missing fields: {missing}"
        )

    # session_id must be consistent across all events
    session_ids = {e.get("session_id") for e in events}
    assert len(session_ids) == 1, (
        f"Expected one consistent session_id, got: {session_ids}"
    )
    assert next(iter(session_ids)), "session_id must be a non-empty string"
