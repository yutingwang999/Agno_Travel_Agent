"""harden-workflow-guardrails section 4: business rules after schema validation."""

import json

import pytest

from app.workflow.business_rules import (
    ValidationContext,
    amounts,
    budget_ceiling_rule,
    check_rules,
    cost_consistency_rule,
    day_count_rule,
    opening_hours_times,
    unsupported_specifics_rule,
)
from app.workflow.output_validator import ItineraryOutput, parse_llm_output


def _itinerary(
    days: int = 3,
    trip_length_days: int | None = None,
    daily_cost: float = 100.0,
    total: float | None = None,
    text: str = "Walk around the harbour",
    tips: list[str] | None = None,
) -> ItineraryOutput:
    return ItineraryOutput(
        destination="Sydney",
        trip_length_days=days if trip_length_days is None else trip_length_days,
        budget_level="moderate",
        travel_style="family",
        daily_itinerary=[
            {"day": d + 1, "morning": text, "afternoon": "Lunch", "evening": "Dinner",
             "estimated_cost_aud": daily_cost}
            for d in range(days)
        ],
        total_estimated_cost_aud=daily_cost * days if total is None else total,
        key_tips=tips or ["Book ahead"],
    )


# ---------------------------------------------------------------------------
# Day count (task 4.2)
# ---------------------------------------------------------------------------


def test_day_count_mismatch_inside_the_itinerary():
    """Spec scenario "Day count mismatch"."""
    message = day_count_rule(_itinerary(days=4, trip_length_days=5), ValidationContext())
    assert message.startswith("Content guardrail failed:")


def test_output_disagrees_with_the_request():
    """Spec scenario "Output disagrees with the request": 5 requested, 3 consistent days."""
    message = day_count_rule(_itinerary(days=3), ValidationContext(requested_trip_length=5))
    assert message.startswith("Content guardrail failed:")
    assert "5 day(s)" in message


def test_day_count_without_request_checks_consistency_only():
    assert day_count_rule(_itinerary(days=3), ValidationContext()) is None


# ---------------------------------------------------------------------------
# Cost consistency (task 4.3)
# ---------------------------------------------------------------------------


def test_totals_disagree():
    """Spec scenario "Totals disagree": daily costs sum to 900, total 1,200."""
    message = cost_consistency_rule(_itinerary(daily_cost=300, total=1200), ValidationContext())
    assert message.startswith("Business rule failed: cost")
    assert "900" in message and "1,200" in message


def test_rounding_tolerated():
    """Spec scenario "Rounding tolerated": daily costs sum to 1,200.40, total 1,200."""
    output = _itinerary(days=3, daily_cost=400, total=1200)
    output.daily_itinerary[0].estimated_cost_aud = 400.40
    assert cost_consistency_rule(output, ValidationContext()) is None


def test_small_total_tolerates_one_dollar():
    assert cost_consistency_rule(_itinerary(days=1, daily_cost=50, total=50.9), ValidationContext()) is None
    assert cost_consistency_rule(_itinerary(days=1, daily_cost=50, total=51.5), ValidationContext()) is not None


# ---------------------------------------------------------------------------
# Budget ceiling (task 4.4)
# ---------------------------------------------------------------------------


def test_budget_trip_over_the_level_default():
    """Spec scenario "Budget trip over the ceiling": 3 days at the budget default (70)."""
    context = ValidationContext(requested_trip_length=3, daily_ceiling=70.0)
    message = budget_ceiling_rule(_itinerary(days=3, daily_cost=80), context)
    assert message.startswith("Business rule failed: budget")


def test_budget_message_states_the_numbers():
    """Spec scenario "Message states the numbers": 3 days, 200 per day, total 1,200."""
    context = ValidationContext(requested_trip_length=3, daily_ceiling=200.0)
    message = budget_ceiling_rule(_itinerary(days=3, daily_cost=400), context)
    assert "1,200" in message and "600" in message
    assert "200 per day" in message and "3 days" in message


def test_user_amount_overrides_the_level():
    """Spec scenario "User amount overrides the level": moderate, 120 a day, 2 days, total 300."""
    from app.workflow.budget import daily_budget_ceiling

    context = ValidationContext(requested_trip_length=2, daily_ceiling=daily_budget_ceiling("moderate", 120))
    assert budget_ceiling_rule(_itinerary(days=2, daily_cost=150), context).startswith(
        "Business rule failed: budget"
    )


def test_luxury_with_an_amount():
    """Spec scenario "Luxury with an amount": 1500 a day, 2 days, total 5,000."""
    from app.workflow.budget import daily_budget_ceiling

    context = ValidationContext(requested_trip_length=2, daily_ceiling=daily_budget_ceiling("luxury", 1500))
    assert budget_ceiling_rule(_itinerary(days=2, daily_cost=2500), context).startswith(
        "Business rule failed: budget"
    )


def test_luxury_without_an_amount_has_no_ceiling():
    """Spec scenario "Luxury without an amount has no ceiling"."""
    from app.workflow.budget import daily_budget_ceiling

    context = ValidationContext(requested_trip_length=2, daily_ceiling=daily_budget_ceiling("luxury", None))
    assert budget_ceiling_rule(_itinerary(days=2, daily_cost=20000), context) is None


def test_total_at_the_ceiling_passes():
    context = ValidationContext(requested_trip_length=3, daily_ceiling=200.0)
    assert budget_ceiling_rule(_itinerary(days=3, daily_cost=200), context) is None


# ---------------------------------------------------------------------------
# Unsupported specifics (task 4.5)
# ---------------------------------------------------------------------------


def test_invented_opening_hours():
    """Spec scenario "Invented opening hours"."""
    output = _itinerary(text="The museum opens at 9:30am, so arrive early")
    message = unsupported_specifics_rule(output, ValidationContext(knowledge_context="The museum has a cafe."))
    assert message.startswith("Business rule failed: unsupported")
    assert "9:30am" in message


def test_schedule_time_is_not_an_opening_hours_statement():
    """Spec scenario "Schedule time is not an opening-hours statement"."""
    output = _itinerary(text="Leave the hotel at 9am and walk to the beach")
    assert unsupported_specifics_rule(output, ValidationContext()) is None


def test_price_taken_from_the_context():
    """Spec scenario "Price taken from the context"."""
    output = _itinerary(text="Climb the lookout ($25 entry)")
    context = ValidationContext(knowledge_context="Tickets: $25 entry for adults.")
    assert unsupported_specifics_rule(output, context) is None


def test_opening_hours_found_in_the_context_in_another_format():
    output = _itinerary(text="The gallery opens at 10am and closes at 5 pm.")
    context = ValidationContext(knowledge_context="Open daily 10:00 to 17:00.")
    assert unsupported_specifics_rule(output, context) is None


def test_retrieval_did_not_run_so_any_price_fails():
    """Spec scenario "Retrieval did not run": an empty context supports no price."""
    output = _itinerary(tips=["An Opal card caps travel at $17.80 a day"])
    message = unsupported_specifics_rule(output, ValidationContext())
    assert message.startswith("Business rule failed: unsupported")
    assert "$17.80" in message


def test_numeric_cost_fields_are_exempt():
    assert unsupported_specifics_rule(_itinerary(daily_cost=123.45), ValidationContext()) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$25", {25.0}),
        ("$ 25.50 per adult", {25.5}),
        ("A$40", {40.0}),
        ("AU$40", {40.0}),
        ("AUD 30", {30.0}),
        ("AUD$30", {30.0}),
        ("about 30 AUD", {30.0}),
        ("1,200 dollars", {1200.0}),
        ("$1,200", {1200.0}),
        ("from $25 to $40", {25.0, 40.0}),
        ("open 7 days, 3 km walk", set()),
    ],
)
def test_amount_formats(text, expected):
    assert amounts(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The museum opens at 9:30am.", {570}),
        ("Open 9am-5pm daily.", {540, 1020}),
        ("It closes at 5.30 p.m. on Sundays.", {1050}),
        ("Opening hours are 08:00 to 16:00.", {480, 960}),
        ("Leave at 9am. The park is open all day.", set()),  # time and keyword in different sentences
        ("Meet the guide at 10am at the gate.", set()),
    ],
)
def test_opening_hours_detection(text, expected):
    assert opening_hours_times(text) == expected


# ---------------------------------------------------------------------------
# Rule list and parse_llm_output (task 4.1)
# ---------------------------------------------------------------------------


def test_every_failing_rule_is_reported_in_order():
    output = _itinerary(days=3, daily_cost=300, total=1200, text="Entry is $25")
    context = ValidationContext(requested_trip_length=3, daily_ceiling=200.0)
    messages = check_rules(output, context)
    assert [m.split(" —")[0] for m in messages] == [
        "Business rule failed: cost",
        "Business rule failed: budget",
        "Business rule failed: unsupported",
    ]


def test_parse_llm_output_applies_the_rules():
    raw = _itinerary(days=2, daily_cost=300).model_dump_json()
    output, errors = parse_llm_output(raw, ValidationContext(requested_trip_length=2, daily_ceiling=200.0))
    assert output is None
    assert errors.startswith("Business rule failed: budget")


def test_parse_llm_output_passes_a_compliant_itinerary():
    raw = json.dumps(_itinerary(days=2, daily_cost=150).model_dump())
    output, errors = parse_llm_output(raw, ValidationContext(requested_trip_length=2, daily_ceiling=200.0))
    assert errors is None and output is not None


def test_request_budget_figures_are_supported():
    """Spec scenario "Budget ceiling repeated": the model restates the request's own ceiling."""
    output = _itinerary(days=5, daily_cost=60, tips=[
        "Shop at supermarkets to keep daily costs under 70 AUD.",
        "The whole trip stays within $350.",
    ])
    context = ValidationContext(requested_trip_length=5, daily_ceiling=70.0)
    assert unsupported_specifics_rule(output, context) is None


def test_other_prices_still_fail_with_a_ceiling():
    output = _itinerary(days=5, daily_cost=60, tips=["A laksa costs $15 at the markets."])
    context = ValidationContext(requested_trip_length=5, daily_ceiling=70.0)
    assert "$15" in unsupported_specifics_rule(output, context)


def test_no_ceiling_means_no_request_figures():
    output = _itinerary(days=2, daily_cost=60, tips=["Keep it under 70 AUD a day."])
    assert unsupported_specifics_rule(output, ValidationContext(requested_trip_length=2)) is not None
