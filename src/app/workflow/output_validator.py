"""Pydantic output schema and validation helpers for the validate_output step.

The expected LLM output structure mirrors the JSON schema embedded in both
prompt templates (``high_confidence_minimal_context`` and
``low_confidence_with_retrieval``):

{
    "destination": string,
    "trip_length_days": integer,
    "budget_level": string,
    "travel_style": string,
    "daily_itinerary": [
        {
            "day": integer,
            "morning": string,
            "afternoon": string,
            "evening": string,
            "estimated_cost_aud": number
        }
    ],
    "total_estimated_cost_aud": number,
    "key_tips": [string]
}
"""

import json
from typing import List

from pydantic import BaseModel, ValidationError


class DailyItineraryItem(BaseModel):
    day: int
    morning: str
    afternoon: str
    evening: str
    estimated_cost_aud: float


class ItineraryOutput(BaseModel):
    destination: str
    trip_length_days: int
    budget_level: str
    travel_style: str
    daily_itinerary: List[DailyItineraryItem]
    total_estimated_cost_aud: float
    key_tips: List[str]


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped its JSON output in them.

    Args:
        text: Raw LLM output string.

    Returns:
        The text with leading/trailing markdown fences removed.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    start = 1  # skip the opening ``` or ```json line
    end = len(lines)
    if lines[-1].strip() == "```":
        end -= 1
    return "\n".join(lines[start:end]).strip()


def parse_llm_output(raw_text: str) -> tuple[ItineraryOutput | None, str | None]:
    """Parse and validate raw LLM text against the ItineraryOutput schema.

    Strips markdown code fences before attempting JSON parsing, then validates
    the parsed object against :class:`ItineraryOutput`.

    Args:
        raw_text: The raw string output from the LLM.

    Returns:
        A tuple of ``(output, errors)`` where:

        - On success: ``(ItineraryOutput, None)``
        - On failure: ``(None, error_string)``
    """
    cleaned = _strip_markdown_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc}"

    try:
        output = ItineraryOutput.model_validate(data)
    except ValidationError as exc:
        return None, str(exc)

    # Content-level guardrail: daily_itinerary length must match trip_length_days.
    # The LLM is asked to produce exactly one entry per day; a mismatch means the
    # output is structurally plausible but content-incorrect and should be retried.
    actual_days = len(output.daily_itinerary)
    if actual_days != output.trip_length_days:
        return None, (
            f"Content guardrail failed: daily_itinerary has {actual_days} "
            f"day(s) but trip_length_days={output.trip_length_days}. "
            f"Expected exactly {output.trip_length_days} daily entry/entries."
        )

    return output, None
