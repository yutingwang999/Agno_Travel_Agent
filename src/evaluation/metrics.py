"""Constraint satisfaction and system metrics computed from request outcomes.

Constraints are checked on planned itineraries only:

- trip length — ``len(daily_itinerary)`` equals the requested ``trip_length``
- budget      — ``total_estimated_cost_aud``, read as AUD per person excluding
                accommodation, is at most the request's daily budget ceiling times
                the trip length; the ceiling is ``form.max_daily_budget_aud`` when the
                entry has one, otherwise the level's default
                (:func:`app.workflow.budget.daily_budget_ceiling`, the function the
                runtime budget rule uses); a request without a ceiling is N/A

System metrics:

- format pass rate — first validation attempt succeeded, over requests that reached
                     validate_output
- retry rate       — corrective retry needed, over the same requests
- error rate       — share of all requests that ended in ``error``
- latency p50/p95  — end-to-end, over requests the workflow ran for (HTTP 200);
                     422 rejections return before the workflow and would skew it

Public API::

    from evaluation.metrics import constraint_rates, system_metrics

    constraint_rates([(entry, outcome), ...])
    system_metrics([outcome, ...])
"""

from app.workflow.budget import daily_budget_ceiling
from evaluation.behaviour import Outcome
from evaluation.dataset import DatasetEntry


def trip_length_ok(entry: DatasetEntry, itinerary: dict) -> bool:
    return len(itinerary.get("daily_itinerary", [])) == entry.form.trip_length


def budget_ok(entry: DatasetEntry, itinerary: dict) -> bool | None:
    """Whether the per-person total is within the request's ceiling; None when it has none."""
    daily_cap = daily_budget_ceiling(entry.form.budget, entry.form.max_daily_budget_aud)
    if daily_cap is None:
        return None
    total = itinerary.get("total_estimated_cost_aud")
    if not isinstance(total, (int, float)):
        return False
    return total <= daily_cap * entry.form.trip_length


def constraint_rates(results: list[tuple[DatasetEntry, Outcome]]) -> dict:
    """Share of planned itineraries satisfying each code-checked constraint."""
    trip, budget = [], []
    budget_not_applicable = 0
    for entry, outcome in results:
        itinerary = outcome.itinerary
        if outcome.behaviour != "plan" or itinerary is None:
            continue
        trip.append(trip_length_ok(entry, itinerary))
        ok = budget_ok(entry, itinerary)
        if ok is None:
            budget_not_applicable += 1
        else:
            budget.append(ok)
    return {
        "planned": len(trip),
        "trip_length_rate": _rate(trip),
        "budget_rate": _rate(budget),
        "budget_entries": len(budget),
        "budget_not_applicable": budget_not_applicable,
    }


def system_metrics(outcomes: list[Outcome]) -> dict:
    validated = [o for o in outcomes if o.degraded_mode is not None]
    latencies = [o.latency_ms for o in outcomes if o.status_code == 200 and o.latency_ms is not None]
    return {
        "requests": len(outcomes),
        "format_pass_rate": _rate([o.degraded_mode is False for o in validated]),
        "retry_rate": _rate([o.degraded_mode is True for o in validated]),
        "error_rate": _rate([o.behaviour == "error" for o in outcomes]),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
    }


def percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile with linear interpolation between ranks; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None
