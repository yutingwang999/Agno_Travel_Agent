"""Request parser (parse-requests, design decisions 2 and 3).

One structured-output call reads a free-text request into ``ParserOutput``;
code then turns that into the form's fields:

- ``destination`` / ``trip_length`` left empty and listed in ``missing`` when
  the sentence does not give them, or gives a trip length outside 1 to
  ``MAX_TRIP_LENGTH_DAYS``;
- ``budget`` defaulted to ``moderate`` and ``travel_style`` to
  ``DEFAULT_TRAVEL_STYLE``, each listed in ``assumptions`` (written by code, so
  they are exactly the defaulted fields).

The injection check, the travel-request refusal and the place-list lookup of
the destination belong to the endpoint (``POST /parse``); this module passes on
``is_travel_request`` and the destination as the model wrote it.

Public API::

    from app.parsing.parser import parse_text, ParserFailure

    result = parse_text(text, db_url=..., api_key=...)
    result.request, result.preferences, result.assumptions, result.missing
"""

from dataclasses import dataclass, replace
from typing import Callable

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.parsing.models import Assumption, ParsedRequest, ParserOutput
from app.workflow.config import MAX_TRIP_LENGTH_DAYS
from app.workflow.intake_model import BudgetLevel
from app.workflow.llm_usage import LLMResult, result_from_response
from app.workflow.template_resolver import TemplateNotFoundError, resolve_template

PARSER_TEMPLATE_KEY = "request_parser"
# Fixed by design decision 2 (flash-lite first); not tied to LLM_MODEL, so a
# generation model comparison does not change the parser.
PARSER_MODEL = "gemini-3.1-flash-lite"
TEXT_PLACEHOLDER = "{text}"

DEFAULT_BUDGET = BudgetLevel.moderate
DEFAULT_TRAVEL_STYLE = "general sightseeing"

PARSER_OUTPUT_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=ParserOutput,
)


class ParserFailure(Exception):
    """The parser could not produce a result; ``POST /parse`` answers 503.

    ``error_type`` is ``template_not_found``, ``template_error`` (the template
    could not be read, e.g. the database is down), ``llm_error`` or
    ``invalid_output``; the template version and token usage are kept for the
    trace when known.
    """

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        template_version: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.template_version = template_version
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class ParseResult:
    """The form's fields as parsed, with what code assumed and what is missing."""

    is_travel_request: bool
    request: ParsedRequest
    preferences: list[str]
    assumptions: list[Assumption]
    missing: list[str]
    template_key: str = PARSER_TEMPLATE_KEY
    template_version: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _clean(value: str | None) -> str | None:
    """Strip *value*; blank counts as unstated."""
    if value is None:
        return None
    return value.strip() or None


def build_parse(output: ParserOutput) -> ParseResult:
    """Apply the range check, the defaults and the assumptions to the model's answer."""
    destination = _clean(output.destination)
    trip_length = output.trip_length
    if trip_length is not None and not 1 <= trip_length <= MAX_TRIP_LENGTH_DAYS:
        trip_length = None

    missing = []
    if destination is None:
        missing.append("destination")
    if trip_length is None:
        missing.append("trip_length")

    assumptions = []
    budget = output.budget
    if budget is None:
        budget = DEFAULT_BUDGET
        assumptions.append(
            Assumption(
                field="budget",
                value=budget.value,
                message=f"No budget level was given, so {budget.value} is assumed.",
            )
        )
    travel_style = _clean(output.travel_style)
    if travel_style is None:
        travel_style = DEFAULT_TRAVEL_STYLE
        assumptions.append(
            Assumption(
                field="travel_style",
                value=travel_style,
                message=f'No travel style was given, so "{travel_style}" is assumed.',
            )
        )

    amount = output.max_daily_budget_aud
    if amount is not None and amount < 1:
        amount = None

    request = ParsedRequest(
        destination=destination,
        trip_length=trip_length,
        budget=budget,
        travel_style=travel_style,
        max_daily_budget_aud=amount,
        notes=_clean(output.notes),
    )
    preferences = [p for p in (_clean(p) for p in output.preferences) if p]
    return ParseResult(
        is_travel_request=output.is_travel_request,
        request=request,
        preferences=preferences,
        assumptions=assumptions,
        missing=missing,
    )


def _call_llm(prompt: str, api_key: str, model: str) -> LLMResult:
    """One structured-output Gemini call with ``ParserOutput`` as the response schema."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=PARSER_OUTPUT_CONFIG,
    )
    return result_from_response(response)


def parse_text(
    text: str,
    *,
    db_url: str,
    api_key: str,
    call_llm: Callable[[str, str, str], LLMResult] | None = None,
) -> ParseResult:
    """Parse *text* with the active ``request_parser`` template.

    *call_llm* defaults to the Gemini call, looked up when called.

    Raises:
        ParserFailure: no active template or it could not be read, the model
            call raised, or its output is not a valid ``ParserOutput``.
    """
    call_llm = call_llm or _call_llm
    try:
        template, version = resolve_template(PARSER_TEMPLATE_KEY, db_url)
    except TemplateNotFoundError as exc:
        raise ParserFailure("template_not_found", str(exc)) from exc
    except Exception as exc:  # database unreachable or similar: the endpoint answers 503
        raise ParserFailure("template_error", str(exc)) from exc

    # A plain replace of the one placeholder: braces in the traveller's text
    # stay as written and are never substituted.
    prompt = template.replace(TEXT_PLACEHOLDER, text)
    try:
        llm = call_llm(prompt, api_key, PARSER_MODEL)
    except Exception as exc:  # any provider error: the endpoint answers 503
        raise ParserFailure("llm_error", str(exc), template_version=version) from exc

    try:
        output = ParserOutput.model_validate_json(llm.text or "")
    except ValidationError as exc:
        raise ParserFailure(
            "invalid_output",
            str(exc),
            template_version=version,
            input_tokens=llm.input_tokens,
            output_tokens=llm.output_tokens,
        ) from exc

    return replace(
        build_parse(output),
        template_version=version,
        input_tokens=llm.input_tokens,
        output_tokens=llm.output_tokens,
    )
