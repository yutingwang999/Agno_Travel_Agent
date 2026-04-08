"""feat/retrieval-decision merge checklist tests.

Verifies:
  - confidence_score >= 0.85 → evaluator returns False (rag_retrieve skipped)
  - confidence_score <  0.85 → evaluator returns True  (rag_retrieve runs)
  - Boundary: exactly 0.85 → returns False (threshold is inclusive)
  - SSE event data field contains routing_decision, confidence_score, threshold
  - Missing cag_match output defaults to retrieval (safe fallback)
  - Malformed cag_match output defaults to retrieval (safe fallback)
  - RETRIEVAL_CONFIDENCE_THRESHOLD constant equals 0.85
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


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_retrieval_decision_evaluator_importable():
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator  # noqa: F401


def test_retrieval_confidence_threshold_constant():
    from app.workflow.steps.retrieval_decision import RETRIEVAL_CONFIDENCE_THRESHOLD

    assert RETRIEVAL_CONFIDENCE_THRESHOLD == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Threshold routing logic
# ---------------------------------------------------------------------------


def test_high_confidence_returns_false(capsys):
    """confidence_score >= 0.85 → evaluator returns False → rag_retrieve skipped."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input(confidence_score=0.90))

    assert result is False


def test_low_confidence_returns_true(capsys):
    """confidence_score < 0.85 → evaluator returns True → rag_retrieve runs."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input(confidence_score=0.50))

    assert result is True


def test_exactly_at_threshold_returns_false(capsys):
    """Boundary: confidence_score == 0.85 → evaluator returns False (inclusive)."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input(confidence_score=0.85))

    assert result is False


def test_just_below_threshold_returns_true(capsys):
    """confidence_score = 0.8499 (just below 0.85) → evaluator returns True."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input(confidence_score=0.8499))

    assert result is True


# ---------------------------------------------------------------------------
# SSE event structure — checklist: routing decision in data field
# ---------------------------------------------------------------------------


def test_sse_event_contains_routing_decision_rag_retrieve(capsys):
    """Checklist: SSE event data contains routing_decision='rag_retrieve' for low confidence."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(confidence_score=0.50))

    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["data"]["routing_decision"] == "rag_retrieve"


def test_sse_event_contains_routing_decision_generate(capsys):
    """Checklist: SSE event data contains routing_decision='generate' for high confidence."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(confidence_score=0.90))

    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["data"]["routing_decision"] == "generate"


def test_sse_event_data_contains_confidence_score(capsys):
    """SSE event data must include the confidence_score that drove the decision."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(confidence_score=0.65))

    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["data"]["confidence_score"] == pytest.approx(0.65)


def test_sse_event_data_contains_threshold(capsys):
    """SSE event data must include the threshold value for traceability."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(confidence_score=0.80))

    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["data"]["threshold"] == pytest.approx(0.85)


def test_sse_event_structure(capsys):
    """SSE event must have session_id, step, status, timestamp, data, error fields."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_step_input(confidence_score=0.80))

    captured = capsys.readouterr()
    event = json.loads(captured.out.strip())

    assert event["step"] == "retrieval_decision"
    assert event["status"] == "completed"
    assert event["session_id"] == "test-session"
    assert "timestamp" in event
    assert "data" in event
    assert "error" in event


# ---------------------------------------------------------------------------
# Fallback behaviour — missing or malformed cag_match output
# ---------------------------------------------------------------------------


def test_missing_cag_match_output_defaults_to_retrieval(capsys):
    """Checklist: no cag_match output → defaults to True (run rag_retrieve, safe default)."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    # StepInput with no previous_step_outputs
    result = retrieval_decision_evaluator(_make_step_input())

    assert result is True


def test_malformed_cag_match_output_defaults_to_retrieval(capsys):
    """Malformed JSON from cag_match → defaults to True (safe fallback)."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    result = retrieval_decision_evaluator(_make_step_input(raw_content="not valid json {{{"))

    assert result is True


def test_missing_confidence_score_in_data_defaults_to_retrieval(capsys):
    """cag_match data without confidence_score key → defaults to 0.0 → retrieval runs."""
    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    # Valid JSON but no confidence_score in data
    raw = json.dumps({"step": "cag_match", "status": "completed", "data": {}})
    result = retrieval_decision_evaluator(_make_step_input(raw_content=raw))

    assert result is True


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
