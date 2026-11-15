"""Schemas of request parsing (parse-requests task 2.1).

The request body of ``POST /parse``, the parser's structured output, and the
``/parse`` response. Pure Pydantic: no DB, no LLM.
"""

import pytest
from pydantic import ValidationError

from app.parsing.models import (
    Assumption,
    ParsedRequest,
    ParseInput,
    ParserOutput,
    ParseResponse,
)
from app.workflow.config import MAX_PARSE_TEXT_LENGTH

# ---------------------------------------------------------------------------
# ParseInput: the request body
# ---------------------------------------------------------------------------


def test_parse_input_keeps_text_stripped():
    assert ParseInput(text="  Three days in Hobart.  ").text == "Three days in Hobart."


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_parse_input_rejects_blank_text(text):
    with pytest.raises(ValidationError):
        ParseInput(text=text)


def test_parse_input_requires_text():
    with pytest.raises(ValidationError):
        ParseInput()


def test_parse_input_accepts_text_at_the_limit():
    assert len(ParseInput(text="a" * MAX_PARSE_TEXT_LENGTH).text) == MAX_PARSE_TEXT_LENGTH


def test_parse_input_rejects_text_over_the_limit():
    with pytest.raises(ValidationError):
        ParseInput(text="a" * (MAX_PARSE_TEXT_LENGTH + 1))


def test_parse_text_limit_is_1000():
    assert MAX_PARSE_TEXT_LENGTH == 1000


# ---------------------------------------------------------------------------
# ParserOutput: what the model returns
# ---------------------------------------------------------------------------


def test_parser_output_allows_every_field_unstated():
    out = ParserOutput(is_travel_request=True)
    assert out.destination is None
    assert out.trip_length is None
    assert out.budget is None
    assert out.max_daily_budget_aud is None
    assert out.travel_style is None
    assert out.notes is None
    assert out.preferences == []


def test_parser_output_keeps_an_out_of_range_trip_length():
    # The 1-14 day range is applied by code, which then lists the field as
    # missing; the schema must not reject the model's answer.
    assert ParserOutput(is_travel_request=True, trip_length=30).trip_length == 30


def test_parser_output_requires_is_travel_request():
    with pytest.raises(ValidationError):
        ParserOutput(destination="sydney")


def test_parser_output_rejects_an_unknown_budget_level():
    with pytest.raises(ValidationError):
        ParserOutput(is_travel_request=True, budget="mid-range")


def test_parser_output_reads_a_full_answer():
    out = ParserOutput.model_validate(
        {
            "is_travel_request": True,
            "destination": "Sydney",
            "trip_length": 3,
            "budget": "moderate",
            "max_daily_budget_aud": None,
            "travel_style": "family sightseeing",
            "notes": "Our kids are 6 and 9.",
            "preferences": ["kid-friendly activities"],
        }
    )
    assert out.budget == "moderate"
    assert out.preferences == ["kid-friendly activities"]


# ---------------------------------------------------------------------------
# ParsedRequest and ParseResponse: what /parse returns
# ---------------------------------------------------------------------------


def test_parsed_request_allows_empty_required_fields():
    req = ParsedRequest(budget="moderate", travel_style="general sightseeing")
    assert req.destination is None
    assert req.trip_length is None


def test_parsed_request_always_has_budget_and_travel_style():
    with pytest.raises(ValidationError):
        ParsedRequest(travel_style="general sightseeing")
    with pytest.raises(ValidationError):
        ParsedRequest(budget="moderate")


def test_parse_response_has_the_specified_shape():
    resp = ParseResponse(
        parse_id="p-1",
        request=ParsedRequest(
            destination="sydney",
            trip_length=3,
            budget="moderate",
            travel_style="family sightseeing",
            notes="Our kids are 6 and 9.",
        ),
        preferences=["kid-friendly activities"],
        assumptions=[],
        missing=[],
    )
    body = resp.model_dump(mode="json")
    assert set(body) == {"parse_id", "request", "preferences", "assumptions", "missing"}
    assert set(body["request"]) == {
        "destination",
        "trip_length",
        "budget",
        "travel_style",
        "max_daily_budget_aud",
        "notes",
    }
    assert body["request"]["budget"] == "moderate"


def test_assumption_has_field_value_and_message():
    a = Assumption(field="budget", value="moderate", message="Budget not stated; assumed moderate.")
    assert a.model_dump() == {
        "field": "budget",
        "value": "moderate",
        "message": "Budget not stated; assumed moderate.",
    }


def test_assumption_only_names_defaulted_fields():
    with pytest.raises(ValidationError):
        Assumption(field="destination", value="sydney", message="x")


def test_missing_only_names_required_fields():
    with pytest.raises(ValidationError):
        ParseResponse(
            parse_id="p-1",
            request=ParsedRequest(budget="moderate", travel_style="general sightseeing"),
            preferences=[],
            assumptions=[],
            missing=["budget"],
        )
