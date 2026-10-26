"""build-evaluation-harness: behaviour classification and the behaviour correctness rate."""

import json

from evaluation.behaviour import (
    behaviour_correctness,
    classify_response,
    is_correct,
    observe,
)
from evaluation.dataset import DatasetEntry


def _sse(*events: dict) -> str:
    return "".join(f"data: {json.dumps(event)}\r\n\r\n" for event in events)


def _event(step: str, status: str = "completed", data: dict | None = None, error: str | None = None) -> dict:
    return {"session_id": "s", "step": step, "status": status, "timestamp": "t", "data": data or {}, "error": error}


PLANNED = _sse(
    _event("intake"),
    _event("generate", data={"raw_llm_output": "{}"}),
    _event("validate_output", data={"itinerary": {"destination": "Sydney"}, "degraded_mode": False}),
)


def _entry(expected: str, tags: list[str] | None = None, entry_id: str = "t001") -> DatasetEntry:
    return DatasetEntry.model_validate({
        "id": entry_id,
        "tags": tags or [],
        "form": {"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "family"},
        "utterance": "3 days in Sydney",
        "gold_slots": {"destination": "sydney", "trip_length_days": 3},
        "expected_behavior": expected,
        "relevant_sections": [],
        "needs_knowledge": False,
    })


# ---------------------------------------------------------------------------
# The four classes
# ---------------------------------------------------------------------------


def test_validated_itinerary_is_plan():
    outcome = classify_response(200, PLANNED)
    assert outcome.behaviour == "plan"
    assert outcome.itinerary == {"destination": "Sydney"}


def test_422_with_reason_code_is_refuse():
    body = json.dumps({"reason": "destination_out_of_scope", "detail": "Paris is not in Australia"})
    outcome = classify_response(422, body)
    assert (outcome.behaviour, outcome.reason) == ("refuse", "destination_out_of_scope")


def test_reason_only_counts_at_the_top_level():
    """The agreed rejection body puts the code at the top level; anything else is not a guard."""
    body = json.dumps({"detail": {"reason": "input_rejected", "message": "..."}})
    assert classify_response(422, body).behaviour == "invalid_input"


def test_fastapi_validation_error_is_invalid_input():
    body = json.dumps({"detail": [{"loc": ["body", "trip_length"], "msg": "trip_length must be at least 1"}]})
    outcome = classify_response(422, body)
    assert (outcome.behaviour, outcome.reason) == ("invalid_input", None)


def test_v010_field_validation_422_is_invalid_input():
    """The real app's 422 for a bad field carries no reason code."""
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).post(
        "/generate",
        json={"destination": "Sydney", "trip_length": 0, "budget": "moderate", "travel_style": "family"},
    )
    assert classify_response(response.status_code, response.text).behaviour == "invalid_input"


def test_error_event_is_error():
    body = _sse(_event("intake"), _event("validate_output", status="error", error="Validation failed after retry"))
    outcome = classify_response(200, body)
    assert outcome.behaviour == "error"
    assert "Validation failed after retry" in outcome.error


def test_stream_without_itinerary_is_error():
    """An aborted stream (no validate_output event) counts as error."""
    outcome = classify_response(200, _sse(_event("intake"), _event("generate")))
    assert outcome.behaviour == "error"


def test_other_status_is_error():
    assert classify_response(500, "Internal Server Error").behaviour == "error"


def test_malformed_sse_is_error():
    assert classify_response(200, "data: {not json").behaviour == "error"


def test_exception_is_error_and_does_not_propagate():
    def send():
        raise RuntimeError("LLM quota exceeded")

    outcome = observe(send)
    assert outcome.behaviour == "error"
    assert "RuntimeError" in outcome.error


def test_exception_group_reports_the_root_cause():
    """A failure inside the streamed workflow arrives wrapped; the root cause must be recorded."""
    def send():
        try:
            raise ConnectionError("503 UNAVAILABLE")
        except ConnectionError as inner:
            wrapped = RuntimeError("step failed")
            wrapped.__cause__ = inner
            raise ExceptionGroup("unhandled errors in a TaskGroup", [wrapped])

    outcome = observe(send)
    assert outcome.behaviour == "error"
    assert "ConnectionError: 503 UNAVAILABLE" in outcome.error
    assert "TaskGroup" not in outcome.error


# ---------------------------------------------------------------------------
# Correctness rate
# ---------------------------------------------------------------------------


def test_out_of_scope_planned_anyway_is_incorrect():
    """Spec scenario: an out_of_scope entry expecting refuse that produces an itinerary."""
    assert is_correct("refuse", "plan") is False
    assert is_correct("refuse", "refuse") is True


def test_clarify_is_always_incorrect():
    for observed in ("plan", "refuse", "invalid_input", "error"):
        assert is_correct("clarify", observed) is False


def test_remaining_entries_evaluated_after_one_raises():
    """Spec scenario: one entry raising is recorded as error; the rest still run."""
    entries = [_entry("plan", entry_id=f"t{i}") for i in range(3)]

    def sender(i):
        def send():
            if i == 1:
                raise ConnectionError("boom")
            return 200, PLANNED
        return send

    outcomes = [observe(sender(i)) for i in range(len(entries))]
    assert [o.behaviour for o in outcomes] == ["plan", "error", "plan"]

    rates = behaviour_correctness(list(zip(entries, outcomes)))
    assert rates["entries"] == 3
    assert rates["overall"] == 2 / 3


def test_correctness_is_reported_per_tag_and_expected_behaviour():
    plan_ok = (_entry("plan"), classify_response(200, PLANNED))
    scope_wrong = (_entry("refuse", ["out_of_scope"]), classify_response(200, PLANNED))
    injection_ok = (
        _entry("refuse", ["prompt_injection"]),
        classify_response(422, json.dumps({"reason": "input_rejected"})),
    )
    clarify = (_entry("clarify", ["contradictory"]), classify_response(200, PLANNED))

    rates = behaviour_correctness([plan_ok, scope_wrong, injection_ok, clarify])

    assert rates["overall"] == 0.5
    assert rates["by_expected_behavior"] == {"clarify": 0.0, "plan": 1.0, "refuse": 0.5}
    assert rates["by_tag"] == {
        "contradictory": 0.0,
        "out_of_scope": 0.0,
        "prompt_injection": 1.0,
        "untagged": 1.0,
    }
