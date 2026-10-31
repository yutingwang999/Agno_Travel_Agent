"""A request's daily budget ceiling (harden-workflow-guardrails, design decision 13).

The ceiling is in AUD per person per day, excluding accommodation: the
request's ``max_daily_budget_aud`` when given, otherwise the default for its
budget level, and none for a level without a default (``luxury``).  The
generate step, the budget rule and the evaluation harness all use
:func:`daily_budget_ceiling`, so they cannot disagree.

Public API:
    daily_budget_ceiling(budget, max_daily_budget_aud) -> float | None
    ceiling_text(ceiling) -> str
"""

from app.workflow.config import DAILY_COST_CAP_AUD_PER_PERSON

NO_CEILING_TEXT = "none set"


def daily_budget_ceiling(budget: str, max_daily_budget_aud: int | None) -> float | None:
    """Return the request's daily ceiling, or None when it has none.

    Args:
        budget:               Budget level (``budget`` / ``moderate`` / ``luxury``).
        max_daily_budget_aud: The amount the user set, or None.
    """
    if max_daily_budget_aud is not None:
        return float(max_daily_budget_aud)
    return DAILY_COST_CAP_AUD_PER_PERSON.get(budget)


def ceiling_text(ceiling: float | None) -> str:
    """Return the value of the ``{daily_budget_ceiling}`` template placeholder."""
    if ceiling is None:
        return NO_CEILING_TEXT
    amount = int(ceiling) if float(ceiling).is_integer() else ceiling
    return f"{amount} AUD per person per day, excluding accommodation"
