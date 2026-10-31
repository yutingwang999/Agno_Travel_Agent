"""Pydantic output schema and validation helpers for the validate_output step.

The expected LLM output structure mirrors the JSON example in the generation
templates; the generate and correction calls also pass ``ItineraryOutput`` to
Gemini as a response schema (``STRUCTURED_OUTPUT_CONFIG``):

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

from google.genai import types
from pydantic import BaseModel, ValidationError

from app.workflow.business_rules import ValidationContext, check_rules


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


# Gemini request config for every call that should return an itinerary (generate
# and the correction retry): JSON constrained by the ItineraryOutput schema.  The
# reply text is still validated by parse_llm_output, whose fence stripping stays
# as the fallback for a provider that ignores the schema (design decision 4).
STRUCTURED_OUTPUT_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=ItineraryOutput,
)


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


def parse_llm_output(
    raw_text: str, context: ValidationContext | None = None
) -> tuple[ItineraryOutput | None, str | None]:
    """Parse raw LLM text, validate it against ItineraryOutput, then apply the business rules.

    Strips markdown code fences before attempting JSON parsing (a fallback for
    providers that ignore the response schema), validates the parsed object
    against :class:`ItineraryOutput`, and runs every rule in
    :data:`app.workflow.business_rules.RULES` with *context*.

    Args:
        raw_text: The raw string output from the LLM.
        context:  What the rules know about the request (requested days, daily
                  ceiling, knowledge context).  None means none of it is known:
                  the day count is checked for internal consistency only, no
                  ceiling applies, and the knowledge context is empty.

    Returns:
        A tuple of ``(output, errors)`` where:

        - On success: ``(ItineraryOutput, None)``
        - On failure: ``(None, error_string)``; when several rules fail, their
          messages are joined with newlines in rule order.
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

    failures = check_rules(output, context or ValidationContext())
    if failures:
        return None, "\n".join(failures)
    return output, None
