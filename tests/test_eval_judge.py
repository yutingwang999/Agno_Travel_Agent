"""build-evaluation-harness: LLM judge plumbing, with the OpenAI client mocked."""

import json
from types import SimpleNamespace

import pytest

from evaluation.judge import (
    Claim,
    DestinationVerdict,
    FaithfulnessVerdict,
    Judge,
    PlaceCheck,
    destination_rate,
    faithfulness_summary,
    itinerary_text,
    knowledge_context,
    load_prompt,
)

ITINERARY = {
    "daily_itinerary": [{"day": 1, "morning": "Opera House tour", "afternoon": "Bondi", "evening": "Dinner"}],
    "key_tips": ["Buy an Opal card"],
}


class FakeClient:
    """Stands in for openai.OpenAI; records prompts and returns a canned verdict."""

    def __init__(self, verdict):
        self.prompts = []
        self.responses = SimpleNamespace(parse=self._parse)
        self._verdict = verdict

    def _parse(self, model, input, text_format):
        self.prompts.append((model, input, text_format))
        return SimpleNamespace(
            output_parsed=self._verdict,
            usage=SimpleNamespace(input_tokens=900, output_tokens=120),
        )


def test_prompts_exist_and_have_placeholders():
    faithfulness = load_prompt("faithfulness", 1)
    assert "{knowledge_context}" in faithfulness and "{itinerary}" in faithfulness
    destination = load_prompt("destination", 1)
    assert "{destination}" in destination and "{trip_length}" in destination


def test_faithfulness_prompt_carries_context_and_itinerary():
    verdict = FaithfulnessVerdict(claims=[Claim(category="named_place", text="Opera House", supported=True)])
    client = FakeClient(verdict)
    call = Judge(client, model="judge-m").faithfulness(ITINERARY, "[Guide to Sydney]\nOpera House ...")

    model, prompt, schema = client.prompts[0]
    assert model == "judge-m"
    assert schema is FaithfulnessVerdict
    assert "[Guide to Sydney]" in prompt and "Opera House tour" in prompt and "Buy an Opal card" in prompt
    assert "{" not in prompt.split("KNOWLEDGE CONTEXT")[1]  # every placeholder substituted
    assert call.verdict == verdict
    assert (call.input_tokens, call.output_tokens) == (900, 120)


def test_faithfulness_without_context_says_so():
    client = FakeClient(FaithfulnessVerdict(claims=[]))
    Judge(client).faithfulness(ITINERARY, "")
    assert "(no knowledge context was given)" in client.prompts[0][1]


def test_destination_prompt_carries_destination_and_length():
    client = FakeClient(DestinationVerdict(places=[]))
    Judge(client).destination(ITINERARY, destination="悉尼", trip_length=4)
    prompt = client.prompts[0][1]
    assert "悉尼" in prompt and "4 days" in prompt


def test_invalid_verdict_is_rejected():
    client = FakeClient({"claims": [{"category": "weather", "text": "sunny", "supported": True}]})
    with pytest.raises(ValueError):
        Judge(client).faithfulness(ITINERARY, "")


def test_default_judge_model_differs_from_generation_model():
    from app.workflow.steps.generate import DEFAULT_LLM_MODEL
    from evaluation.judge import DEFAULT_JUDGE_MODEL

    assert DEFAULT_JUDGE_MODEL != DEFAULT_LLM_MODEL


def test_knowledge_context_matches_generate_formatting():
    event = {"step": "rag_retrieve", "status": "completed",
             "data": {"retrieved_context": [{"title": "Guide to Sydney", "chunk_text": "Bondi ..."},
                                            {"title": "", "chunk_text": "Untitled text"}]}}
    context = knowledge_context([{"step": "intake"}, event])
    assert "[Guide to Sydney]\nBondi ..." in context
    assert "Untitled text" in context


def test_knowledge_context_empty_without_retrieval():
    assert knowledge_context([{"step": "intake"}, {"step": "generate"}]) == ""


def test_itinerary_text_lists_days_and_tips():
    text = itinerary_text(ITINERARY)
    assert text.startswith("Day 1: morning: Opera House tour")
    assert text.endswith("Tip: Buy an Opal card")


def test_faithfulness_summary_splits_by_context():
    """Unsupported claims are counted; with and without context are reported separately."""
    with_ctx = FaithfulnessVerdict(claims=[
        Claim(category="named_place", text="Opera House", supported=True),
        Claim(category="opening_hours", text="opens 9am", supported=False),
    ])
    without_ctx = FaithfulnessVerdict(claims=[Claim(category="price", text="$25 entry", supported=False)])
    empty = FaithfulnessVerdict(claims=[])

    summary = faithfulness_summary([(with_ctx, True), (without_ctx, False), (empty, False)])

    assert summary["overall"] == {"itineraries": 3, "claims": 3, "supported_share": pytest.approx(1 / 3)}
    assert summary["with_context"]["supported_share"] == 0.5
    assert summary["without_context"] == {"itineraries": 2, "claims": 1, "supported_share": 0.0}


def test_destination_rate_requires_every_place_in_destination():
    ok = DestinationVerdict(places=[PlaceCheck(name="Bondi", in_destination=True, reason="Sydney beach")])
    off = DestinationVerdict(places=[
        PlaceCheck(name="Bondi", in_destination=True, reason="..."),
        PlaceCheck(name="Hosier Lane", in_destination=False, reason="Melbourne"),
    ])
    assert destination_rate([ok, off]) == 0.5
    assert destination_rate([]) is None


def test_verdicts_round_trip_through_json():
    verdict = FaithfulnessVerdict(claims=[Claim(category="transport", text="20-min ferry", supported=False)])
    assert FaithfulnessVerdict.model_validate(json.loads(verdict.model_dump_json())) == verdict
