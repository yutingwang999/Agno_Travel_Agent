"""feat/intake merge checklist tests.

Verifies:
  - Pydantic model covers all 4 required fields: destination, trip_length,
    budget, travel_style
  - Missing required field raises ValidationError (maps to 422, not 500)
  - Normalised fields (e.g. lowercased destination) are present in workflow
    state (SSE event data) after step 1
  - intake_executor emits an SSE event with the normalised values in `data`

No DB or Docker required — intake validation is pure Python.
"""

import json

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_FIELDS = {
    "session_id": "test-session",
    "destination": "Sydney",
    "trip_length": 5,
    "budget": "moderate",
    "travel_style": "family",
}


def _make_step_input(overrides: dict | None = None):
    from agno.workflow.types import StepInput

    additional_data = {**VALID_FIELDS, **(overrides or {})}
    return StepInput(
        input="plan a trip",
        additional_data=additional_data,
    )


# ---------------------------------------------------------------------------
# TravelRequest model — field coverage
# ---------------------------------------------------------------------------


def test_travel_request_model_importable():
    from app.workflow.intake_model import TravelRequest  # noqa: F401


def test_budget_level_enum_importable():
    from app.workflow.intake_model import BudgetLevel  # noqa: F401


def test_budget_level_enum_has_three_values():
    from app.workflow.intake_model import BudgetLevel

    assert set(BudgetLevel) == {BudgetLevel.budget, BudgetLevel.moderate, BudgetLevel.luxury}


def test_travel_request_accepts_all_four_fields():
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest(
        destination="Melbourne",
        trip_length=7,
        budget="luxury",
        travel_style="romantic",
    )
    assert request.destination == "melbourne"
    assert request.trip_length == 7
    assert request.budget == "luxury"
    assert request.travel_style == "romantic"


# ---------------------------------------------------------------------------
# Field normalisation
# ---------------------------------------------------------------------------


def test_destination_normalised_to_lowercase():
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest(
        destination="CAIRNS",
        trip_length=3,
        budget="budget",
        travel_style="adventure",
    )
    assert request.destination == "cairns"


def test_destination_leading_trailing_whitespace_stripped():
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest(
        destination="  Gold Coast  ",
        trip_length=4,
        budget="moderate",
        travel_style="family",
    )
    assert request.destination == "gold coast"


# ---------------------------------------------------------------------------
# ValidationError on missing / invalid required fields (→ 422, not 500)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["destination", "trip_length", "budget", "travel_style"],
)
def test_missing_required_field_raises_validation_error(missing_field):
    """Each of the 4 required fields must produce ValidationError when absent."""
    from app.workflow.intake_model import TravelRequest

    fields = {
        "destination": "Sydney",
        "trip_length": 5,
        "budget": "moderate",
        "travel_style": "family",
    }
    del fields[missing_field]

    with pytest.raises(ValidationError):
        TravelRequest(**fields)


def test_empty_destination_raises_validation_error():
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="", trip_length=3, budget="budget", travel_style="solo")


def test_zero_trip_length_raises_validation_error():
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="Darwin", trip_length=0, budget="budget", travel_style="solo")


def test_negative_trip_length_raises_validation_error():
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="Darwin", trip_length=-1, budget="budget", travel_style="solo")


def test_empty_budget_raises_validation_error():
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="Perth", trip_length=3, budget="", travel_style="solo")


def test_invalid_budget_value_raises_validation_error():
    """Any string not in BudgetLevel enum must raise ValidationError (→ 422)."""
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="Perth", trip_length=3, budget="low", travel_style="solo")


@pytest.mark.parametrize("valid_budget", ["budget", "moderate", "luxury"])
def test_all_budget_enum_values_accepted(valid_budget):
    """All three BudgetLevel values must be accepted without error."""
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest(
        destination="Sydney", trip_length=3, budget=valid_budget, travel_style="family"
    )
    assert request.budget == valid_budget


def test_empty_travel_style_raises_validation_error():
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(destination="Perth", trip_length=3, budget="moderate", travel_style="")


# ---------------------------------------------------------------------------
# intake_executor — SSE event output
# ---------------------------------------------------------------------------


def test_intake_executor_returns_sse_event():
    from app.workflow.steps.intake import intake_executor

    output = intake_executor(_make_step_input())
    assert output.content is not None
    event = json.loads(output.content)

    assert event["step"] == "intake"
    assert event["status"] == "completed"
    assert event["session_id"] == "test-session"
    assert "timestamp" in event


def test_intake_executor_data_contains_all_four_normalised_fields():
    """Normalised fields must be present in SSE event data for downstream steps."""
    from app.workflow.steps.intake import intake_executor

    output = intake_executor(
        _make_step_input(
            {
                "destination": "BRISBANE",
                "trip_length": 4,
                "budget": "luxury",
                "travel_style": "romantic",
            }
        )
    )
    event = json.loads(output.content)
    data = event["data"]

    # Checklist: all 4 fields present in workflow state after step 1
    assert data["destination"] == "brisbane"  # normalised to lowercase
    assert data["trip_length"] == 4
    assert data["budget"] == "luxury"
    assert data["travel_style"] == "romantic"


def test_intake_executor_destination_lowercased_in_state():
    """Checklist item: normalised destination is lowercase in workflow state."""
    from app.workflow.steps.intake import intake_executor

    output = intake_executor(_make_step_input({"destination": "Alice Springs"}))
    event = json.loads(output.content)

    assert event["data"]["destination"] == "alice springs"


def test_intake_executor_raises_validation_error_on_missing_field():
    """Checklist item: missing required field raises ValidationError (→ 422)."""
    from agno.workflow.types import StepInput
    from app.workflow.steps.intake import intake_executor

    step_input = StepInput(
        input="plan a trip",
        additional_data={
            "session_id": "bad-session",
            # destination intentionally omitted
            "trip_length": 5,
            "budget": "moderate",
            "travel_style": "family",
        },
    )

    with pytest.raises(ValidationError):
        intake_executor(step_input)


@pytest.mark.parametrize(
    "missing_field",
    ["destination", "trip_length", "budget", "travel_style"],
)
def test_intake_executor_raises_validation_error_for_each_missing_field(missing_field):
    """All 4 required fields must produce ValidationError when missing."""
    from agno.workflow.types import StepInput
    from app.workflow.steps.intake import intake_executor

    additional_data = {**VALID_FIELDS}
    del additional_data[missing_field]

    step_input = StepInput(input="plan a trip", additional_data=additional_data)

    with pytest.raises(ValidationError):
        intake_executor(step_input)


# ---------------------------------------------------------------------------
# model_validate ignores extra fields (e.g. session_id)
# ---------------------------------------------------------------------------


def test_travel_request_ignores_extra_fields():
    """session_id and other additional_data fields must not cause errors."""
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest.model_validate(
        {
            "destination": "Hobart",
            "trip_length": 2,
            "budget": "budget",
            "travel_style": "solo",
            "session_id": "should-be-ignored",
            "unexpected_key": "also-ignored",
        }
    )
    assert request.destination == "hobart"


# ---------------------------------------------------------------------------
# max_daily_budget_aud (harden-workflow-guardrails task 5.7)
# ---------------------------------------------------------------------------

_BASE = {"destination": "Sydney", "trip_length": 2, "budget": "moderate", "travel_style": "family"}


def test_no_budget_amount_is_null_in_the_intake_event():
    """Spec scenario "No budget amount"."""
    from app.workflow.steps.intake import intake_executor

    data = json.loads(intake_executor(_make_step_input()).content)["data"]
    assert data["max_daily_budget_aud"] is None


def test_budget_amount_is_carried_by_the_intake_event():
    from app.workflow.steps.intake import intake_executor

    data = json.loads(intake_executor(_make_step_input({"max_daily_budget_aud": 150})).content)["data"]
    assert data["max_daily_budget_aud"] == 150


@pytest.mark.parametrize("amount", [0, -10, 85.5])
def test_invalid_budget_amount_rejected(amount):
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError):
        TravelRequest(**_BASE, max_daily_budget_aud=amount)


@pytest.mark.parametrize("amount", [1, 150, 20000, 1_000_000])
def test_budget_amount_accepted_without_upper_bound(amount):
    from app.workflow.intake_model import TravelRequest

    assert TravelRequest(**_BASE, max_daily_budget_aud=amount).max_daily_budget_aud == amount


def test_amount_above_the_level_default_is_accepted():
    """Spec scenario "Amount above the level default": budget level, 500 a day."""
    from app.workflow.budget import daily_budget_ceiling
    from app.workflow.intake_model import TravelRequest

    request = TravelRequest(**{**_BASE, "budget": "budget"}, max_daily_budget_aud=500)
    assert daily_budget_ceiling(request.budget, request.max_daily_budget_aud) == 500


# ---------------------------------------------------------------------------
# Trip length upper bound
# ---------------------------------------------------------------------------


def test_fourteen_days_accepted():
    from app.workflow.intake_model import TravelRequest

    assert TravelRequest(**{**_BASE, "trip_length": 14}).trip_length == 14


@pytest.mark.parametrize("days", [15, 30, 1000])
def test_trip_longer_than_fourteen_days_rejected(days):
    from app.workflow.intake_model import TravelRequest

    with pytest.raises(ValidationError, match="trip_length must be at most 14"):
        TravelRequest(**{**_BASE, "trip_length": days})


def test_upper_bound_matches_config():
    from app.workflow.config import MAX_TRIP_LENGTH_DAYS

    assert MAX_TRIP_LENGTH_DAYS == 14
