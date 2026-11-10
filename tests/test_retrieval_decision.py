"""retrieval_decision step tests.

Verifies (rebuild-rag, interim routing):
  - every request routes to rag_retrieve, whatever the confidence (spec "High confidence still retrieves")
  - the SSE event data holds routing_decision and confidence_score, and no threshold
  - missing or malformed cag_match output still routes to retrieval
  - the event travels in StepOutput.content; nothing is printed (true-sse-streaming)
"""

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cag_match_sse_content(confidence_score: float) -> str:
    """Build the JSON string that cag_match_executor writes to StepOutput.content."""
    return json.dumps(
        {
            "session_id": "test-session",
            "step": "cag_match",
            "status": "completed",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "data": {
                "matched_category": "family",
                "confidence_score": confidence_score,
                "tone": "friendly and family-oriented",
                "constraints": "Activities must be suitable for children.",
                "is_fallback": False,
            },
            "error": None,
        }
    )


def _make_step_input(confidence_score: float | None = None, raw_content: str | None = None):
    """Build a StepInput with a fake cag_match previous step output.

    Args:
        confidence_score: If provided, builds a valid cag_match SSE JSON with
                          this score.
        raw_content:      If provided, uses this string verbatim as
                          cag_match StepOutput.content (for malformed cases).
    """
    from agno.workflow.types import StepInput, StepOutput

    additional_data = {"session_id": "test-session"}

    if confidence_score is not None or raw_content is not None:
        content = (
            raw_content
            if raw_content is not None
            else _make_cag_match_sse_content(confidence_score)  # type: ignore[arg-type]
        )
        cag_output = StepOutput(step_name="cag_match", content=content)
        return StepInput(
            additional_data=additional_data,
            previous_step_outputs={"cag_match": cag_output},
        )

    # No previous step output at all
    return StepInput(additional_data=additional_data)


def _decide(step_input) -> dict:
    """Run retrieval_decision_executor and return its parsed SSE event."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_executor

    return json.loads(retrieval_decision_executor(step_input).content)


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_retrieval_decision_step_importable():
    from app.workflow.steps.retrieval_decision import retrieval_decision_executor  # noqa: F401


def test_threshold_constant_is_gone():
    """The confidence threshold no longer exists (spec: Retrieval routing threshold removed)."""
    import app.workflow.config as config
    import app.workflow.steps.retrieval_decision as step

    assert not hasattr(config, "RETRIEVAL_CONFIDENCE_THRESHOLD")
    assert not hasattr(step, "RETRIEVAL_CONFIDENCE_THRESHOLD")


# ---------------------------------------------------------------------------
# Interim routing: always retrieve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidence_score", [0.95, 0.90, 0.85, 0.50, 0.0])
def test_every_confidence_routes_to_retrieval(confidence_score):
    """Spec scenario "High confidence still retrieves"."""
    event = _decide(_make_step_input(confidence_score=confidence_score))

    assert event["data"]["routing_decision"] == "rag_retrieve"


# ---------------------------------------------------------------------------
# SSE event structure — checklist: routing decision in data field
# ---------------------------------------------------------------------------


def test_sse_event_data_contains_confidence_score():
    """SSE event data must include the confidence_score that drove the decision."""
    event = _decide(_make_step_input(confidence_score=0.65))

    assert event["data"]["confidence_score"] == pytest.approx(0.65)


def test_sse_event_data_has_no_threshold():
    """The event reports the decision and the confidence only."""
    event = _decide(_make_step_input(confidence_score=0.80))

    assert set(event["data"]) == {"routing_decision", "confidence_score"}


def test_sse_event_structure():
    """SSE event must have session_id, step, status, timestamp, data, error fields."""
    event = _decide(_make_step_input(confidence_score=0.80))

    assert event["step"] == "retrieval_decision"
    assert event["status"] == "completed"
    assert event["session_id"] == "test-session"
    assert "timestamp" in event
    assert "data" in event
    assert "error" in event


@pytest.mark.parametrize("confidence_score", [0.50, 0.90])
def test_routing_decision_prints_nothing(capsys, confidence_score):
    """Spec scenario "No stdout side effect": the event is not written to stdout."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_executor

    retrieval_decision_executor(_make_step_input(confidence_score=confidence_score))

    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Fallback behaviour — missing or malformed cag_match output
# ---------------------------------------------------------------------------


def test_missing_cag_match_output_defaults_to_retrieval():
    """Checklist: no cag_match output → rag_retrieve (safe default)."""
    event = _decide(_make_step_input())

    assert event["data"]["routing_decision"] == "rag_retrieve"


def test_malformed_cag_match_output_defaults_to_retrieval():
    """Malformed JSON from cag_match → rag_retrieve (safe fallback)."""
    event = _decide(_make_step_input(raw_content="not valid json {{{"))

    assert event["data"]["routing_decision"] == "rag_retrieve"


def test_missing_confidence_score_in_data_defaults_to_retrieval():
    """cag_match data without confidence_score key → defaults to 0.0 → retrieval runs."""
    raw = json.dumps({"step": "cag_match", "status": "completed", "data": {}})
    event = _decide(_make_step_input(raw_content=raw))

    assert event["data"]["routing_decision"] == "rag_retrieve"


# ---------------------------------------------------------------------------
# _extract_confidence_score unit tests
# ---------------------------------------------------------------------------


def test_extract_confidence_score_returns_correct_value():
    from app.workflow.steps.retrieval_decision import _extract_confidence_score

    step_input = _make_step_input(confidence_score=0.82)
    score = _extract_confidence_score(step_input)

    assert score == pytest.approx(0.82)


def test_extract_confidence_score_returns_zero_when_no_previous_outputs():
    from app.workflow.steps.retrieval_decision import _extract_confidence_score

    step_input = _make_step_input()  # no previous outputs
    score = _extract_confidence_score(step_input)

    assert score == pytest.approx(0.0)
