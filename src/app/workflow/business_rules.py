"""Business rules checked after schema validation (harden-workflow-guardrails, decision 5).

Each rule is a pure function ``rule(output, context) -> str | None`` returning a
failure message, or None when the rule passes.  The message names the rule and
the values involved, so the correction call knows what to fix:

- ``Content guardrail failed: ...``          — day count (internal and against the request)
- ``Business rule failed: cost ...``         — daily costs do not add up to the total
- ``Business rule failed: budget ...``       — total above the request's ceiling
- ``Business rule failed: unsupported ...``  — opening hours or prices not in the knowledge context

Public API:
    ValidationContext
    RULES
    check_rules(output, context) -> list[str]
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # output_validator imports this module to run the rules
    from app.workflow.output_validator import ItineraryOutput

# Cost consistency: daily costs may differ from the total by this much.
COST_TOLERANCE_AUD = 1.0
COST_TOLERANCE_SHARE = 0.01


@dataclass(frozen=True)
class ValidationContext:
    """What the rules know about the request besides the itinerary itself.

    Attributes:
        requested_trip_length: ``trip_length`` from the intake event, or None
                               when it cannot be read (internal check only).
        daily_ceiling:         The request's daily budget ceiling in AUD per
                               person, or None when it has none.
        knowledge_context:     ``chunk_text`` of every retrieved chunk joined,
                               or "" when retrieval did not run.
    """

    requested_trip_length: int | None = None
    daily_ceiling: float | None = None
    knowledge_context: str = ""


def _aud(amount: float) -> str:
    """Format an amount as in the failure messages: 1,200 or 1,200.50."""
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"


# ---------------------------------------------------------------------------
# Day count
# ---------------------------------------------------------------------------


def day_count_rule(output: "ItineraryOutput", context: ValidationContext) -> str | None:
    actual = len(output.daily_itinerary)
    if actual != output.trip_length_days:
        return (
            f"Content guardrail failed: daily_itinerary has {actual} day(s) but "
            f"trip_length_days={output.trip_length_days}. "
            f"Expected exactly {output.trip_length_days} daily entry/entries."
        )
    requested = context.requested_trip_length
    if requested is not None and output.trip_length_days != requested:
        return (
            f"Content guardrail failed: the request asks for {requested} day(s) but the "
            f"itinerary has trip_length_days={output.trip_length_days}. "
            f"Plan exactly {requested} days."
        )
    return None


# ---------------------------------------------------------------------------
# Cost consistency and budget ceiling
# ---------------------------------------------------------------------------


def cost_consistency_rule(output: "ItineraryOutput", context: ValidationContext) -> str | None:
    daily_sum = sum(day.estimated_cost_aud for day in output.daily_itinerary)
    total = output.total_estimated_cost_aud
    allowed = max(COST_TOLERANCE_AUD, COST_TOLERANCE_SHARE * abs(total))
    if abs(daily_sum - total) <= allowed:
        return None
    return (
        f"Business rule failed: cost — the daily estimated_cost_aud values add up to "
        f"{_aud(daily_sum)} AUD but total_estimated_cost_aud is {_aud(total)} AUD. "
        f"The total must equal the sum of the daily costs."
    )


def budget_ceiling_rule(output: "ItineraryOutput", context: ValidationContext) -> str | None:
    if context.daily_ceiling is None:
        return None
    days = context.requested_trip_length or output.trip_length_days
    trip_ceiling = context.daily_ceiling * days
    total = output.total_estimated_cost_aud
    if total <= trip_ceiling:
        return None
    return (
        f"Business rule failed: budget — total {_aud(total)} AUD per person exceeds the "
        f"ceiling of {_aud(trip_ceiling)} AUD ({_aud(context.daily_ceiling)} per day × "
        f"{days} days). Costs are AUD per person, excluding accommodation; plan within "
        f"the ceiling."
    )


# ---------------------------------------------------------------------------
# Unsupported specifics: opening hours and prices
# ---------------------------------------------------------------------------

# A clock time: 9am, 9 am, 9:30am, 9.30 p.m., 09:30, 17:00.
_TIME = re.compile(
    r"\b(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)(?![a-z])"
    r"|\b(?P<h24>\d{1,2}):(?P<m24>\d{2})\b",
    re.IGNORECASE,
)
_OPENING_WORD = re.compile(r"\b(?:open|opens|opening|close|closes)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|\n")

# An amount of money: $25, $ 25.50, A$40, AU$40, AUD 30, AUD$30, 30 AUD, 1,200 dollars.
_AMOUNT = re.compile(
    r"(?:\bAUD\s*\$?|\bAU\$|\bA\$|\$)\s*(?P<pre>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<pre_c>\d{1,2}))?"
    r"|\b(?P<post>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<post_c>\d{1,2}))?\s*(?:AUD|dollars?)\b",
    re.IGNORECASE,
)


def _minutes(match: re.Match) -> int | None:
    """Minutes after midnight for a matched time, or None if it is not a valid time."""
    if match.group("h") is not None:
        hour, minute = int(match.group("h")), int(match.group("m") or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        pm = match.group("ap").lower().startswith("p")
        return (hour % 12 + (12 if pm else 0)) * 60 + minute
    hour, minute = int(match.group("h24")), int(match.group("m24"))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _clock(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}{f':{minute:02d}' if minute else ''}{suffix}"


def opening_hours_times(text: str) -> set[int]:
    """Times stated in opening-hours sentences: a time in the same sentence as open/close."""
    times: set[int] = set()
    for sentence in _SENTENCE_END.split(text):
        if not _OPENING_WORD.search(sentence):
            continue
        for match in _TIME.finditer(sentence):
            minutes = _minutes(match)
            if minutes is not None:
                times.add(minutes)
    return times


def all_times(text: str) -> set[int]:
    return {m for m in (_minutes(match) for match in _TIME.finditer(text)) if m is not None}


def amounts(text: str) -> set[float]:
    """Every currency amount in *text*, as a number."""
    found: set[float] = set()
    for match in _AMOUNT.finditer(text):
        whole = (match.group("pre") or match.group("post")).replace(",", "")
        cents = match.group("pre_c") or match.group("post_c") or "0"
        found.add(float(f"{whole}.{cents}"))
    return found


def _text_fields(output: "ItineraryOutput") -> str:
    parts = [f"{day.morning}\n{day.afternoon}\n{day.evening}" for day in output.daily_itinerary]
    return "\n".join(parts + list(output.key_tips))


def _request_amounts(output: "ItineraryOutput", context: ValidationContext) -> set[float]:
    """The budget figures the request itself gives: daily ceiling and trip ceiling."""
    if context.daily_ceiling is None:
        return set()
    days = context.requested_trip_length or output.trip_length_days
    return {float(context.daily_ceiling), float(context.daily_ceiling * days)}


def unsupported_specifics_rule(output: "ItineraryOutput", context: ValidationContext) -> str | None:
    """Opening hours and prices in the text fields must also appear in the knowledge context.

    Times and amounts are compared by value, so "9:30am" matches "9.30 am" and
    "$25" matches "A$25" or "AUD 25".  Numeric cost fields are exempt, and so
    are the request's own budget figures — the daily ceiling and the trip
    ceiling — which the generation template states and the model may repeat
    ("stay under 70 AUD a day").
    """
    text = _text_fields(output)
    context_times = all_times(context.knowledge_context)
    context_amounts = amounts(context.knowledge_context) | _request_amounts(output, context)
    bad_times = sorted(opening_hours_times(text) - context_times)
    bad_amounts = sorted(amounts(text) - context_amounts)
    if not bad_times and not bad_amounts:
        return None
    found = []
    if bad_times:
        found.append("opening hours " + ", ".join(_clock(t) for t in bad_times))
    if bad_amounts:
        found.append("prices " + ", ".join(f"${_aud(a)}" for a in bad_amounts))
    return (
        f"Business rule failed: unsupported — {'; '.join(found)} in the itinerary text "
        f"are not in the reference information. Remove opening hours and prices that the "
        f"reference information does not state (estimated_cost_aud values are fine)."
    )


Rule = Callable[["ItineraryOutput", ValidationContext], str | None]

RULES: list[Rule] = [
    day_count_rule,
    cost_consistency_rule,
    budget_ceiling_rule,
    unsupported_specifics_rule,
]


def check_rules(output: "ItineraryOutput", context: ValidationContext) -> list[str]:
    """Run every rule; return the failure messages in rule order (empty when all pass)."""
    return [message for rule in RULES if (message := rule(output, context)) is not None]
