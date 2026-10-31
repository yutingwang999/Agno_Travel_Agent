"""build-evaluation-harness: constraint satisfaction and system metrics."""

import pytest

from evaluation.behaviour import Outcome
from evaluation.dataset import DatasetEntry
from evaluation.metrics import (
    budget_ok,
    constraint_rates,
    percentile,
    system_metrics,
    trip_length_ok,
)



def _entry(budget: str = "budget", days: int = 3, amount: int | None = None) -> DatasetEntry:
    form = {"destination": "Sydney", "trip_length": days, "budget": budget, "travel_style": "family"}
    if amount is not None:
        form["max_daily_budget_aud"] = amount
    return DatasetEntry.model_validate({
        "id": "t001",
        "tags": [],
        "form": form,
        "utterance": "...",
        "gold_slots": {"destination": "sydney", "trip_length_days": days},
        "expected_behavior": "plan",
        "relevant_sections": [],
        "needs_knowledge": False,
    })


def _itinerary(days: int, total: float) -> dict:
    return {
        "daily_itinerary": [{"day": d} for d in range(1, days + 1)],
        "total_estimated_cost_aud": total,
    }


def _planned(itinerary: dict, degraded: bool = False, latency: float = 100.0) -> Outcome:
    events = [{"step": "validate_output", "status": "completed",
               "data": {"itinerary": itinerary, "degraded_mode": degraded}}]
    return Outcome("plan", 200, events=events, latency_ms=latency)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_trip_length_matches_request():
    assert trip_length_ok(_entry(days=3), _itinerary(3, 100)) is True
    assert trip_length_ok(_entry(days=3), _itinerary(2, 100)) is False


def test_budget_exceeded():
    """Spec scenario: a 3-day budget request above 3 x the budget cap fails."""
    assert budget_ok(_entry("budget", 3), _itinerary(3, 210.0)) is True
    assert budget_ok(_entry("budget", 3), _itinerary(3, 210.01)) is False


def test_budget_for_level_without_cap_is_not_applicable():
    """Spec scenario: luxury has no cap, so the budget constraint is N/A."""
    assert budget_ok(_entry("luxury", 3), _itinerary(3, 99999)) is None


def test_budget_without_a_numeric_total_fails():
    assert budget_ok(_entry("moderate", 2), {"daily_itinerary": [], "total_estimated_cost_aud": None}) is False


def test_constraint_rates_skip_non_planned_and_exclude_na_from_budget():
    results = [
        (_entry("budget", 3), _planned(_itinerary(3, 150))),       # both ok
        (_entry("moderate", 2), _planned(_itinerary(3, 900))),     # wrong length, over budget
        (_entry("luxury", 4), _planned(_itinerary(4, 5000))),      # length ok, budget N/A
        (_entry("budget", 3), Outcome("refuse", 422, reason="x")),  # not planned
    ]
    rates = constraint_rates(results)
    assert rates["planned"] == 3
    assert rates["trip_length_rate"] == pytest.approx(2 / 3)
    assert rates["budget_rate"] == 0.5
    assert rates["budget_entries"] == 2
    assert rates["budget_not_applicable"] == 1


def test_default_caps_come_from_config():
    from app.workflow.config import DAILY_COST_CAP_AUD_PER_PERSON

    assert DAILY_COST_CAP_AUD_PER_PERSON == {"budget": 70.0, "moderate": 200.0}
    assert budget_ok(_entry("moderate", 1), _itinerary(1, 200.0)) is True


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------


def test_format_pass_and_retry_rates_over_validated_requests():
    outcomes = [
        _planned(_itinerary(3, 1), degraded=False),
        _planned(_itinerary(3, 1), degraded=False),
        _planned(_itinerary(3, 1), degraded=True),
        Outcome("refuse", 422, reason="x", latency_ms=1.0),  # never reached validate_output
    ]
    metrics = system_metrics(outcomes)
    assert metrics["format_pass_rate"] == pytest.approx(2 / 3)
    assert metrics["retry_rate"] == pytest.approx(1 / 3)


def test_error_rate_over_all_requests():
    outcomes = [_planned(_itinerary(1, 1)), Outcome("error", error="boom"), Outcome("refuse", 422, reason="x")]
    assert system_metrics(outcomes)["error_rate"] == pytest.approx(1 / 3)


def test_latency_percentiles_use_only_workflow_runs():
    outcomes = [_planned(_itinerary(1, 1), latency=ms) for ms in (100, 200, 300, 400, 500)]
    outcomes.append(Outcome("refuse", 422, reason="x", latency_ms=1.0))
    metrics = system_metrics(outcomes)
    assert metrics["latency_p50_ms"] == 300
    assert metrics["latency_p95_ms"] == pytest.approx(480)


def test_percentile_interpolates_and_handles_empty():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([7], 95) == 7
    assert percentile([], 50) is None


def test_observe_records_latency():
    from evaluation.behaviour import observe

    outcome = observe(lambda: (500, "x"))
    assert outcome.behaviour == "error"
    assert outcome.latency_ms is not None and outcome.latency_ms >= 0


def test_amount_in_the_request():
    """Spec scenario "Amount in the request": luxury, 1500 a day, 2 days, total 5,000."""
    assert budget_ok(_entry("luxury", 2, amount=1500), _itinerary(2, 5000)) is False
    assert budget_ok(_entry("luxury", 2, amount=1500), _itinerary(2, 3000)) is True


def test_amount_overrides_the_level_default():
    assert budget_ok(_entry("moderate", 2, amount=120), _itinerary(2, 300)) is False   # level allows 400
    assert budget_ok(_entry("budget", 2, amount=500), _itinerary(2, 900)) is True      # level allows 140


def test_luxury_without_an_amount_is_not_applicable():
    """Spec scenario "Level without a cap"."""
    assert budget_ok(_entry("luxury", 2), _itinerary(2, 99999)) is None
