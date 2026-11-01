"""feat/retrieval-decision merge checklist tests.

Verifies:
  - confidence_score >= 0.85 → routing_decision "generate" (rag_retrieve skipped)
  - confidence_score <  0.85 → routing_decision "rag_retrieve" (rag_retrieve runs)
  - Boundary: exactly 0.85 → "generate" (threshold is inclusive)
  - SSE event data field contains routing_decision, confidence_score, threshold
  - Missing cag_match output defaults to retrieval (safe fallback)
  - Malformed cag_match output defaults to retrieval (safe fallback)
  - RETRIEVAL_CONFIDENCE_THRESHOLD constant equals 0.85
  - The event travels in StepOutput.content; nothing is printed (true-sse-streaming)
  - The Condition evaluator only reads the decision back from that event
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


def _make_decision_step_input(raw_content: str | None):
    """Build a StepInput whose retrieval_decision output is ``raw_content``."""
    from agno.workflow.types import StepInput, StepOutput

    if raw_content is None:
        return StepInput(additional_data={"session_id": "test-session"})
    return StepInput(
        additional_data={"session_id": "test-session"},
        previous_step_outputs={
            "retrieval_decision": StepOutput(step_name="retrieval_decision", content=raw_content)
        },
    )


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_retrieval_decision_step_functions_importable():
    from app.workflow.steps.retrieval_decision import (  # noqa: F401
        needs_retrieval,
        retrieval_decision_executor,
    )


def test_retrieval_confidence_threshold_constant():
    from app.workflow.steps.retrieval_decision import RETRIEVAL_CONFIDENCE_THRESHOLD

    assert RETRIEVAL_CONFIDENCE_THRESHOLD == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Threshold routing logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence_score", "expected"),
    [
        (0.90, "generate"),
        (0.50, "rag_retrieve"),
        (0.85, "generate"),  # boundary: threshold is inclusive
        (0.8499, "rag_retrieve"),
    ],
)
def test_routing_decision_follows_threshold(confidence_score, expected):
    event = _decide(_make_step_input(confidence_score=confidence_score))

    assert event["data"]["routing_decision"] == expected


# ---------------------------------------------------------------------------
# SSE event structure — checklist: routing decision in data field
# ---------------------------------------------------------------------------


def test_sse_event_data_contains_confidence_score():
    """SSE event data must include the confidence_score that drove the decision."""
    event = _decide(_make_step_input(confidence_score=0.65))

    assert event["data"]["confidence_score"] == pytest.approx(0.65)


def test_sse_event_data_contains_threshold():
    """SSE event data must include the threshold value for traceability."""
    event = _decide(_make_step_input(confidence_score=0.80))

    assert event["data"]["threshold"] == pytest.approx(0.85)


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
    from app.workflow.steps.retrieval_decision import needs_retrieval, retrieval_decision_executor

    output = retrieval_decision_executor(_make_step_input(confidence_score=confidence_score))
    needs_retrieval(_make_decision_step_input(output.content))

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
# needs_retrieval — the Condition evaluator reads the decision back
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence_score", "expected"),
    [(0.90, False), (0.50, True)],
)
def test_needs_retrieval_follows_the_decision_event(confidence_score, expected):
    from app.workflow.steps.retrieval_decision import needs_retrieval, retrieval_decision_executor

    output = retrieval_decision_executor(_make_step_input(confidence_score=confidence_score))

    assert needs_retrieval(_make_decision_step_input(output.content)) is expected


@pytest.mark.parametrize("raw_content", [None, "not valid json {{{", "[]", json.dumps({"data": {}})])
def test_needs_retrieval_defaults_to_retrieval(raw_content):
    """Missing or malformed decision output → True (run retrieval, safe default)."""
    from app.workflow.steps.retrieval_decision import needs_retrieval

    assert needs_retrieval(_make_decision_step_input(raw_content)) is True


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
