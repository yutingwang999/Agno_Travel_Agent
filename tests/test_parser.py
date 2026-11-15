"""Parser module (parse-requests task 2.3).

The model is faked: each test gives the JSON the parser model would return and
checks what code makes of it (defaults, assumptions, the 1-14 day range,
``missing``), plus the call itself (template, prompt, failures). No DB, no LLM.
"""

import json

import pytest

from app.parsing import parser
from app.parsing.parser import (
    DEFAULT_TRAVEL_STYLE,
    PARSER_MODEL,
    PARSER_TEMPLATE_KEY,
    ParserFailure,
    build_parse,
    parse_text,
)
from app.parsing.models import ParserOutput
from app.workflow.llm_usage import LLMResult
from app.workflow.template_resolver import TemplateNotFoundError

TEMPLATE = "Read the message.\nMessage:\n{text}\n"


def _output(**fields) -> ParserOutput:
    return ParserOutput(is_travel_request=True, **fields)


# ---------------------------------------------------------------------------
# build_parse: what code does with the model's answer
# ---------------------------------------------------------------------------


def test_complete_sentence_needs_no_default():
    result = build_parse(
        _output(
            destination="Sydney",
            trip_length=3,
            budget="moderate",
            travel_style="family with kids",
            notes="Our kids are 6 and 9.",
            preferences=["family", "kids"],
        )
    )
    assert result.request.destination == "Sydney"
    assert result.request.trip_length == 3
    assert result.request.budget == "moderate"
    assert result.request.travel_style == "family with kids"
    assert result.assumptions == []
    assert result.missing == []
    assert result.preferences == ["family", "kids"]


def test_no_destination_is_left_empty_and_missing():
    result = build_parse(_output(trip_length=5, budget="budget", travel_style="beach"))
    assert result.request.destination is None
    assert result.request.trip_length == 5
    assert result.missing == ["destination"]


def test_blank_destination_counts_as_none():
    assert build_parse(_output(destination="  ", trip_length=2)).missing == ["destination"]


def test_no_trip_length_is_left_empty_and_missing():
    result = build_parse(_output(destination="Hobart"))
    assert result.request.trip_length is None
    assert result.missing == ["trip_length"]


def test_both_required_fields_missing_in_form_order():
    assert build_parse(_output()).missing == ["destination", "trip_length"]


@pytest.mark.parametrize("days", [0, 15, 30, -2])
def test_trip_length_outside_1_to_14_is_left_empty_and_missing(days):
    result = build_parse(_output(destination="Cairns", trip_length=days))
    assert result.request.trip_length is None
    assert result.missing == ["trip_length"]


@pytest.mark.parametrize("days", [1, 14])
def test_trip_length_at_the_range_ends_is_kept(days):
    assert build_parse(_output(destination="Cairns", trip_length=days)).request.trip_length == days


def test_unstated_budget_defaults_to_moderate_with_one_assumption():
    result = build_parse(_output(destination="Gold Coast", trip_length=9, travel_style="slow pace"))
    assert result.request.budget == "moderate"
    assert [a.field for a in result.assumptions] == ["budget"]
    assert result.assumptions[0].value == "moderate"
    assert result.assumptions[0].message


def test_stated_budget_is_kept_without_assumption():
    result = build_parse(_output(destination="Melbourne", trip_length=3, budget="budget", travel_style="coffee"))
    assert result.request.budget == "budget"
    assert result.assumptions == []


def test_unstated_travel_style_gets_the_general_default_with_one_assumption():
    result = build_parse(_output(destination="Perth", trip_length=2, budget="luxury"))
    assert result.request.travel_style == DEFAULT_TRAVEL_STYLE
    assert [a.field for a in result.assumptions] == ["travel_style"]
    assert result.assumptions[0].value == DEFAULT_TRAVEL_STYLE


def test_blank_travel_style_counts_as_unstated():
    result = build_parse(_output(destination="Perth", trip_length=2, budget="luxury", travel_style=" "))
    assert result.request.travel_style == DEFAULT_TRAVEL_STYLE


def test_both_defaults_give_two_assumptions_and_nothing_else():
    result = build_parse(_output(destination="Darwin", trip_length=2))
    assert [a.field for a in result.assumptions] == ["budget", "travel_style"]


def test_daily_amount_is_kept():
    result = build_parse(_output(destination="Brisbane", trip_length=2, budget="budget", max_daily_budget_aud=50))
    assert result.request.max_daily_budget_aud == 50


@pytest.mark.parametrize("amount", [0, -10])
def test_non_positive_daily_amount_is_dropped(amount):
    # /generate rejects an amount below 1, so the form must not carry one.
    result = build_parse(_output(destination="Brisbane", trip_length=2, max_daily_budget_aud=amount))
    assert result.request.max_daily_budget_aud is None


def test_notes_are_kept_apart_from_the_other_fields():
    result = build_parse(
        _output(
            destination="Sydney",
            trip_length=3,
            budget="moderate",
            travel_style="family",
            notes="  Our kids are 6 and 9.  ",
        )
    )
    assert result.request.notes == "Our kids are 6 and 9."
    assert result.request.travel_style == "family"


def test_blank_notes_count_as_none():
    assert build_parse(_output(destination="Sydney", trip_length=3, notes="   ")).request.notes is None


def test_blank_preferences_are_dropped():
    result = build_parse(_output(destination="Sydney", trip_length=3, preferences=[" art ", "", "  "]))
    assert result.preferences == ["art"]


def test_travel_request_flag_is_passed_on():
    assert build_parse(ParserOutput(is_travel_request=False)).is_travel_request is False


# ---------------------------------------------------------------------------
# parse_text: template, prompt, model call, failures
# ---------------------------------------------------------------------------


class FakeLLM:
    """Records the prompt and model, and returns a fixed answer or raises."""

    def __init__(self, answer: dict | str | Exception):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt: str, api_key: str, model: str) -> LLMResult:
        self.calls.append((prompt, model))
        if isinstance(self.answer, Exception):
            raise self.answer
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return LLMResult(text=text, input_tokens=120, output_tokens=40)


@pytest.fixture
def active_template(monkeypatch):
    calls = []

    def fake_resolve(template_key, db_url, version=None):
        calls.append((template_key, version))
        return TEMPLATE, 1

    monkeypatch.setattr(parser, "resolve_template", fake_resolve)
    return calls


def _parse(llm, text="Three days in Hobart."):
    return parse_text(text, db_url="postgresql://unused", api_key="unused", call_llm=llm)


def test_parse_text_uses_the_active_request_parser_template(active_template):
    _parse(FakeLLM({"is_travel_request": True, "destination": "Hobart", "trip_length": 3}))
    assert active_template == [(PARSER_TEMPLATE_KEY, None)]
    assert PARSER_TEMPLATE_KEY == "request_parser"


def test_parse_text_makes_one_call_to_flash_lite_with_the_text_in_the_prompt(active_template):
    llm = FakeLLM({"is_travel_request": True})
    _parse(llm, "Three days in Hobart.")
    assert len(llm.calls) == 1
    prompt, model = llm.calls[0]
    assert model == PARSER_MODEL == "gemini-3.1-flash-lite"
    assert prompt == "Read the message.\nMessage:\nThree days in Hobart.\n"


def test_braces_in_the_text_are_left_as_written(active_template):
    llm = FakeLLM({"is_travel_request": True})
    _parse(llm, "Trip to {destination} with {text}")
    assert llm.calls[0][0].endswith("Message:\nTrip to {destination} with {text}\n")


def test_parse_text_returns_the_built_result_with_usage_and_template(active_template):
    result = _parse(FakeLLM({"is_travel_request": True, "destination": "Hobart", "trip_length": 3}))
    assert result.request.destination == "Hobart"
    assert result.missing == []
    assert [a.field for a in result.assumptions] == ["budget", "travel_style"]
    assert (result.template_key, result.template_version) == ("request_parser", 1)
    assert (result.input_tokens, result.output_tokens) == (120, 40)


def test_no_active_template_is_a_parser_failure(monkeypatch):
    def missing(template_key, db_url, version=None):
        raise TemplateNotFoundError("No active template found")

    monkeypatch.setattr(parser, "resolve_template", missing)
    llm = FakeLLM({"is_travel_request": True})
    with pytest.raises(ParserFailure) as exc:
        _parse(llm)
    assert exc.value.error_type == "template_not_found"
    assert llm.calls == []


def test_model_exception_is_a_parser_failure(active_template):
    with pytest.raises(ParserFailure) as exc:
        _parse(FakeLLM(RuntimeError("503 UNAVAILABLE")))
    assert exc.value.error_type == "llm_error"
    assert exc.value.template_version == 1


@pytest.mark.parametrize("answer", ["not json", '{"destination": "Hobart"}', '{"is_travel_request": true, "budget": "mid"}'])
def test_unusable_model_output_is_a_parser_failure(active_template, answer):
    with pytest.raises(ParserFailure) as exc:
        _parse(FakeLLM(answer))
    assert exc.value.error_type == "invalid_output"
    assert (exc.value.input_tokens, exc.value.output_tokens) == (120, 40)
