"""feat/validate-output merge checklist tests.

Verifies:
  - output_validator and validate_output_executor are importable
  - parse_llm_output accepts valid JSON and returns ItineraryOutput
  - parse_llm_output rejects bad JSON with an error string
  - parse_llm_output rejects wrong schema with an error string
  - parse_llm_output strips markdown code fences before parsing
  - valid output passes step 6 without modification (degraded_mode=False)
  - invalid output triggers exactly one retry, not two or zero
  - retry success sets degraded_mode=True
  - two consecutive failures return structured error — no unhandled 500
  - degraded_mode=True present whenever a retry was attempted
  - SSE event structure matches DESIGN.md section 9
"""

import json
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

VALID_ITINERARY = {
    "destination": "Sydney",
    "trip_length_days": 3,
    "budget_level": "moderate",
    "travel_style": "family",
    "daily_itinerary": [
        {
            "day": 1,
            "morning": "Visit Bondi Beach",
            "afternoon": "Lunch at Bondi Icebergs",
            "evening": "Dinner in Surry Hills",
            "estimated_cost_aud": 150.0,
        }
    ],
    "total_estimated_cost_aud": 450.0,
    "key_tips": ["Book ahead", "Use Opal card"],
}

VALID_ITINERARY_JSON = json.dumps(VALID_ITINERARY)


def _make_generate_sse(raw_llm_output: str, session_id: str = "test-session") -> str:
    """Build the JSON string that generate_executor writes to StepOutput.content."""
    return json.dumps(
        {
            "session_id": session_id,
            "step": "generate",
            "status": "completed",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "data": {
                "raw_llm_output": raw_llm_output,
                "prompt_template_key": "high_confidence_minimal_context",
                "prompt_template_version": 1,
            },
            "error": None,
        }
    )


def _make_step_input(raw_llm_output: str = VALID_ITINERARY_JSON, session_id: str = "test-session"):
    """Build a StepInput whose generate step output contains raw_llm_output."""
    from agno.workflow.types import StepInput, StepOutput

    generate_output = StepOutput(
        step_name="generate",
        content=_make_generate_sse(raw_llm_output, session_id),
    )
    return StepInput(
        additional_data={"session_id": session_id},
        previous_step_outputs={"generate": generate_output},
    )


CORRECTION_TEMPLATE_TEXT = (
    "Fix this output.\n"
    "Errors: {validation_errors}\n"
    "Bad output: {raw_llm_output}\n"
    "Return JSON only."
)


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_output_validator_importable():
    from app.workflow.output_validator import ItineraryOutput, parse_llm_output  # noqa: F401


def test_validate_output_executor_importable():
    from app.workflow.steps.validate_output import validate_output_executor  # noqa: F401


# ---------------------------------------------------------------------------
# parse_llm_output — unit tests (no DB, no LLM)
# ---------------------------------------------------------------------------


def test_parse_valid_json_returns_itinerary_output():
    """Valid JSON matching the schema returns (ItineraryOutput, None)."""
    from app.workflow.output_validator import ItineraryOutput, parse_llm_output

    output, errors = parse_llm_output(VALID_ITINERARY_JSON)

    assert errors is None
    assert isinstance(output, ItineraryOutput)
    assert output.destination == "Sydney"
    assert output.trip_length_days == 3
    assert len(output.daily_itinerary) == 1
    assert output.key_tips == ["Book ahead", "Use Opal card"]


def test_parse_invalid_json_returns_error():
    """Malformed JSON returns (None, error_string)."""
    from app.workflow.output_validator import parse_llm_output

    output, errors = parse_llm_output("{not valid json}")

    assert output is None
    assert errors is not None
    assert "JSON parse error" in errors


def test_parse_wrong_schema_returns_error():
    """Valid JSON with wrong keys returns (None, validation_error_string)."""
    from app.workflow.output_validator import parse_llm_output

    output, errors = parse_llm_output(json.dumps({"foo": "bar"}))

    assert output is None
    assert errors is not None


def test_parse_strips_markdown_fences():
    """Markdown code fences are removed before parsing."""
    from app.workflow.output_validator import parse_llm_output

    fenced = f"```json\n{VALID_ITINERARY_JSON}\n```"
    output, errors = parse_llm_output(fenced)

    assert errors is None
    assert output is not None
    assert output.destination == "Sydney"


def test_parse_strips_plain_fences():
    """Plain ``` fences (no language tag) are also removed."""
    from app.workflow.output_validator import parse_llm_output

    fenced = f"```\n{VALID_ITINERARY_JSON}\n```"
    output, errors = parse_llm_output(fenced)

    assert errors is None
    assert output is not None


def test_parse_missing_required_field_returns_error():
    """Output missing a required field (e.g. key_tips) fails validation."""
    from app.workflow.output_validator import parse_llm_output

    incomplete = dict(VALID_ITINERARY)
    del incomplete["key_tips"]

    output, errors = parse_llm_output(json.dumps(incomplete))

    assert output is None
    assert errors is not None


def test_parse_model_dump_round_trips():
    """ItineraryOutput.model_dump() produces JSON-serialisable output."""
    from app.workflow.output_validator import parse_llm_output

    output, _ = parse_llm_output(VALID_ITINERARY_JSON)
    dumped = output.model_dump()

    assert dumped["destination"] == "Sydney"
    assert dumped["daily_itinerary"][0]["day"] == 1
    # Verify it serialises without error
    json.dumps(dumped)


# ---------------------------------------------------------------------------
# validate_output_executor — valid first attempt (no retry)
# ---------------------------------------------------------------------------


def _run_executor(
    raw_llm_output: str = VALID_ITINERARY_JSON,
    session_id: str = "test-session",
    correction_template: str = CORRECTION_TEMPLATE_TEXT,
    retry_llm_output: str = VALID_ITINERARY_JSON,
):
    """Run validate_output_executor with DB and LLM mocked.

    Returns the decoded SSE event dict and the mock LLM call object.
    """
    from app.workflow.steps.validate_output import validate_output_executor

    step_input = _make_step_input(raw_llm_output=raw_llm_output, session_id=session_id)

    mock_llm = MagicMock(return_value=retry_llm_output)

    with (
        patch(
            "app.workflow.steps.validate_output.resolve_template",
            return_value=(correction_template, 1),
        ),
        patch("app.workflow.steps.validate_output._call_llm", mock_llm),
        patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql://fake",
                "GEMINI_API_KEY": "fake-key",
                "LLM_MODEL": "gemini-2.0-flash",
            },
        ),
    ):
        result = validate_output_executor(step_input)

    event = json.loads(result.content)
    return event, mock_llm


def test_valid_output_passes_without_retry():
    """Checklist: valid LLM output passes step 6 without modification."""
    event, mock_llm = _run_executor(raw_llm_output=VALID_ITINERARY_JSON)

    assert event["status"] == "completed"
    assert event["data"]["degraded_mode"] is False
    assert "itinerary" in event["data"]
    # No retry — LLM must NOT have been called again
    mock_llm.assert_not_called()


def test_valid_output_itinerary_fields_present():
    """Validated itinerary contains all required top-level fields."""
    event, _ = _run_executor(raw_llm_output=VALID_ITINERARY_JSON)

    itinerary = event["data"]["itinerary"]
    for field in ("destination", "trip_length_days", "budget_level", "travel_style",
                  "daily_itinerary", "total_estimated_cost_aud", "key_tips"):
        assert field in itinerary, f"Missing field: {field}"


def test_valid_output_sse_event_structure():
    """SSE event must include all required fields from DESIGN.md section 9."""
    event, _ = _run_executor()

    for field in ("session_id", "step", "status", "timestamp", "data", "error"):
        assert field in event, f"Missing SSE field: {field}"


def test_valid_output_sse_step_is_validate_output():
    event, _ = _run_executor()
    assert event["step"] == "validate_output"


def test_valid_output_session_id_propagated():
    event, _ = _run_executor(session_id="abc-123")
    assert event["session_id"] == "abc-123"


# ---------------------------------------------------------------------------
# validate_output_executor — invalid first attempt, retry succeeds
# ---------------------------------------------------------------------------


def test_invalid_output_triggers_exactly_one_retry():
    """Checklist: invalid output triggers exactly one retry, not two or zero."""
    invalid_output = '{"broken": true}'

    event, mock_llm = _run_executor(
        raw_llm_output=invalid_output,
        retry_llm_output=VALID_ITINERARY_JSON,
    )

    # LLM called exactly once (the retry)
    assert mock_llm.call_count == 1


def test_retry_success_sets_degraded_mode_true():
    """Checklist: degraded_mode=True when retry was attempted (even on success)."""
    invalid_output = '{"broken": true}'

    event, _ = _run_executor(
        raw_llm_output=invalid_output,
        retry_llm_output=VALID_ITINERARY_JSON,
    )

    assert event["status"] == "completed"
    assert event["data"]["degraded_mode"] is True
    assert "itinerary" in event["data"]


def test_retry_corrective_prompt_uses_db_template():
    """The corrective prompt text must come from resolve_template (not hardcoded)."""
    from app.workflow.steps.validate_output import validate_output_executor

    step_input = _make_step_input(raw_llm_output='{"bad": "data"}')

    resolve_called = {"called": False}

    def fake_resolve(template_key, db_url):
        resolve_called["called"] = True
        assert template_key == "validate_output_correction"
        return (CORRECTION_TEMPLATE_TEXT, 1)

    with (
        patch("app.workflow.steps.validate_output.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.validate_output._call_llm", return_value=VALID_ITINERARY_JSON),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        validate_output_executor(step_input)

    assert resolve_called["called"], "resolve_template was not called — correction prompt may be hardcoded"


# ---------------------------------------------------------------------------
# validate_output_executor — both attempts fail
# ---------------------------------------------------------------------------


def test_two_failures_return_error_sse_not_exception():
    """Checklist: after two failures, response is a structured error — no unhandled 500."""
    invalid_output = '{"broken": true}'

    event, mock_llm = _run_executor(
        raw_llm_output=invalid_output,
        retry_llm_output=invalid_output,  # retry also fails
    )

    # Exactly one retry attempt
    assert mock_llm.call_count == 1
    # Structured error, not a crash
    assert event["status"] == "error"
    assert event["error"] is not None


def test_two_failures_set_degraded_mode_true():
    """Checklist: degraded_mode=True present whenever retry was attempted."""
    invalid_output = '{"broken": true}'

    event, _ = _run_executor(
        raw_llm_output=invalid_output,
        retry_llm_output=invalid_output,
    )

    assert event["data"]["degraded_mode"] is True


def test_two_failures_sse_step_is_validate_output():
    invalid_output = '{"broken": true}'
    event, _ = _run_executor(raw_llm_output=invalid_output, retry_llm_output=invalid_output)
    assert event["step"] == "validate_output"


def test_two_failures_error_field_contains_message():
    invalid_output = '{"broken": true}'
    event, _ = _run_executor(raw_llm_output=invalid_output, retry_llm_output=invalid_output)
    assert isinstance(event["error"], str)
    assert len(event["error"]) > 0


# ---------------------------------------------------------------------------
# validate_output_executor — correction template missing
# ---------------------------------------------------------------------------


def test_missing_correction_template_returns_structured_error():
    """When correction template is not in the DB, return structured error not exception."""
    from app.workflow.steps.validate_output import validate_output_executor
    from app.workflow.template_resolver import TemplateNotFoundError

    step_input = _make_step_input(raw_llm_output='{"broken": true}')

    with (
        patch(
            "app.workflow.steps.validate_output.resolve_template",
            side_effect=TemplateNotFoundError("not found"),
        ),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        result = validate_output_executor(step_input)

    event = json.loads(result.content)

    assert event["status"] == "error"
    assert event["data"]["degraded_mode"] is True
    assert event["error"] is not None


# ---------------------------------------------------------------------------
# _extract_raw_llm_output unit tests
# ---------------------------------------------------------------------------


def test_extract_raw_llm_output_reads_from_generate_step():
    """_extract_raw_llm_output correctly reads from the generate SSE event."""
    from app.workflow.steps.validate_output import _extract_raw_llm_output

    step_input = _make_step_input(raw_llm_output="some raw output")
    result = _extract_raw_llm_output(step_input)

    assert result == "some raw output"


def test_extract_raw_llm_output_returns_empty_when_step_missing():
    """Returns empty string when generate step output is absent."""
    from agno.workflow.types import StepInput
    from app.workflow.steps.validate_output import _extract_raw_llm_output

    step_input = StepInput(additional_data={"session_id": "x"}, previous_step_outputs=None)
    result = _extract_raw_llm_output(step_input)

    assert result == ""


# ---------------------------------------------------------------------------
# _build_correction_prompt unit tests
# ---------------------------------------------------------------------------


def test_build_correction_prompt_substitutes_variables():
    """_build_correction_prompt fills in {validation_errors} and {raw_llm_output}."""
    from app.workflow.steps.validate_output import _build_correction_prompt

    template = "Errors: {validation_errors}\nOutput: {raw_llm_output}\nFix it."
    result = _build_correction_prompt(
        template_text=template,
        raw_llm_output='{"bad": true}',
        validation_errors="Field 'destination' is required",
    )

    assert "Field 'destination' is required" in result
    assert '{"bad": true}' in result


def test_build_correction_prompt_leaves_json_braces_intact():
    """Literal { } in the JSON schema example within the template are untouched."""
    from app.workflow.steps.validate_output import _build_correction_prompt

    template = 'Fix this.\n{validation_errors}\nExpected:\n{\n  "destination": string\n}'
    result = _build_correction_prompt(
        template_text=template,
        raw_llm_output="bad",
        validation_errors="error",
    )

    assert '{\n  "destination": string\n}' in result
