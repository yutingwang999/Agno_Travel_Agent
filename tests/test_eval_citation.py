"""Citation accuracy (spec "Citation accuracy metric"): judge input, verdict handling and the summary.

All text is made up.
"""

import re
from types import SimpleNamespace

from evaluation.judge import (
    CitationCheck,
    CitationVerdict,
    Judge,
    citation_by_coverage,
    citation_pairs,
    citation_summary,
    cited_blocks,
    load_prompt,
)
from evaluation.rejudge import rejudge_record, rejudged_metrics
from evaluation.cost import Pricing

CHUNKS = [
    {"title": "Testville/Harbour", "chunk_text": "Ferries leave Testville Quay every hour for the harbour cruise."},
    {"title": "Testville/Museums", "chunk_text": "The Testville Museum shows ship models and maps."},
    {"title": "Testville", "chunk_text": "Testville has a night market on Thursdays."},
]
EVENTS = [
    {"step": "rag_retrieve", "status": "completed", "data": {"retrieved_context": CHUNKS}},
]


def _itinerary(*days):
    return {"daily_itinerary": [
        {"day": n, "morning": m, "afternoon": "Free time", "evening": "Dinner", "sources": s}
        for n, m, s in days
    ], "key_tips": []}


class FakeClient:
    def __init__(self, checks):
        self.prompts = []
        self.checks = checks
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, model, input, text_format):
        self.prompts.append(input)
        assert text_format is CitationVerdict
        return SimpleNamespace(output_parsed=CitationVerdict(checks=self.checks),
                               usage=SimpleNamespace(input_tokens=300, output_tokens=40))


def _check(day, cid, supported, item="", reason="r"):
    return CitationCheck(day=day, id=cid, supported=supported, item=item, reason=reason)


def test_cited_blocks_use_generate_numbering_and_keep_only_cited_ids():
    itinerary = _itinerary((1, "Harbour cruise", ["S1"]), (2, "Night market", ["S3", "S9"]))
    blocks = cited_blocks(EVENTS, itinerary)
    assert list(blocks) == ["S1", "S3"]  # S2 not cited; S9 was never in the context
    assert blocks["S1"].startswith("Testville/Harbour\nFerries leave")


def test_no_retrieval_means_no_blocks():
    assert cited_blocks([], _itinerary((1, "Walk", ["S1"]))) == {}


def test_pairs_follow_itinerary_order_once_each():
    itinerary = _itinerary((1, "a", ["S3", "S1", "S3"]), (2, "b", ["S1"]), (3, "c", []))
    assert citation_pairs(itinerary, {"S1", "S3"}) == [(1, "S3"), (1, "S1"), (2, "S1")]


def test_nothing_cited_makes_no_judge_call():
    client = FakeClient([])
    call = Judge(client).citation(_itinerary((1, "Walk", [])), {})
    assert call.verdict.checks == [] and (call.input_tokens, call.output_tokens) == (0, 0)
    assert client.prompts == []


def test_prompt_shows_cited_blocks_and_the_days_that_cite_them():
    itinerary = _itinerary((1, "Harbour cruise from Testville Quay", ["S1"]), (2, "Lazy day", []),
                           (3, "Night market", ["S3"]))
    client = FakeClient([_check(1, "S1", True, "harbour cruise"), _check(3, "S3", True, "night market")])
    Judge(client).citation(itinerary, cited_blocks(EVENTS, itinerary))
    prompt = client.prompts[0]
    assert "[S1] Testville/Harbour\nFerries leave" in prompt and "[S3] Testville\n" in prompt
    assert "Testville Museum" not in prompt  # S2 is not cited
    assert "Day 1 (cites S1): morning: Harbour cruise from Testville Quay" in prompt
    assert "Day 2" not in prompt  # a day citing nothing is not asked about


def test_verdict_keeps_one_check_per_asked_pair():
    itinerary = _itinerary((1, "Harbour cruise", ["S1"]), (2, "Museum", ["S2"]))
    client = FakeClient([
        _check(2, "S2", True, "museum"),
        _check(1, "S1", False),
        _check(1, "S1", True),        # a second answer for the same pair: the first is kept
        _check(4, "S3", True),        # never asked: dropped
    ])
    call = Judge(client).citation(itinerary, cited_blocks(EVENTS, itinerary))
    assert [(c.day, c.id, c.supported) for c in call.verdict.checks] == [(1, "S1", False), (2, "S2", True)]


def test_citation_that_does_not_support_its_day_counts_as_unsupported():
    """Spec scenario: a day about a harbour cruise cites a chunk about museum exhibitions."""
    itinerary = _itinerary((1, "Harbour cruise", ["S2"]))
    verdict = CitationVerdict(checks=[_check(1, "S2", False)])
    summary = citation_summary([(verdict, itinerary, cited_blocks(EVENTS, itinerary), True)])
    assert summary["citations"] == 1 and summary["supported_share"] == 0.0


def test_summary_shares_and_missing_checks():
    cited = _itinerary((1, "Harbour cruise", ["S1"]), (2, "Museum", ["S2"]), (3, "Rest", []))
    uncited = _itinerary((1, "Walk", []), (2, "Walk", []))
    no_context = _itinerary((1, "Walk", []))
    items = [
        (CitationVerdict(checks=[_check(1, "S1", True)]), cited, cited_blocks(EVENTS, cited), True),  # (2, S2) missing
        (CitationVerdict(checks=[]), uncited, {}, True),
        (CitationVerdict(checks=[]), no_context, {}, False),
    ]
    summary = citation_summary(items)
    assert summary["itineraries"] == 3 and summary["itineraries_citing"] == 1
    assert summary["citations"] == 1 and summary["supported_share"] == 1.0 and summary["missing_checks"] == 1
    # days of itineraries with context only: 3 + 2, of which 2 cite something
    assert summary["days_with_context"] == 5 and summary["days_citing_share"] == 2 / 5


def test_summary_by_coverage():
    a = _itinerary((1, "Harbour cruise", ["S1"]))
    b = _itinerary((1, "Walk", ["S3"]))
    groups = citation_by_coverage([
        (CitationVerdict(checks=[_check(1, "S1", True)]), a, cited_blocks(EVENTS, a), True, "city"),
        (CitationVerdict(checks=[_check(1, "S3", False)]), b, cited_blocks(EVENTS, b), True, "national_only"),
    ])
    assert groups["city"]["supported_share"] == 1.0 and groups["national_only"]["supported_share"] == 0.0


def test_empty_summary():
    summary = citation_summary([])
    assert summary["supported_share"] is None and summary["days_citing_share"] is None


def test_prompt_file_has_only_its_placeholders():
    text = load_prompt("citation", 1)
    assert set(re.findall(r"\{(\w+)\}", text)) == {"blocks", "days"}
    assert text.count("{") == text.count("}") == 2


def _record(itinerary):
    from evaluation.judge import itinerary_text, knowledge_context

    events = EVENTS + [{"step": "validate_output", "status": "completed", "data": {"itinerary": itinerary}}]
    return {
        "entry_id": "e1", "corpus_coverage": "city",
        "form": {"destination": "Testville", "trip_length": 2, "budget": "moderate", "travel_style": "harbours"},
        "outcome": {"events": events},
        "judge": {"faithfulness": {"itinerary_text": itinerary_text(itinerary),
                                   "knowledge_context": knowledge_context(events), "verdict": {"claims": []},
                                   "input_tokens": 1, "output_tokens": 1},
                  "destination": None, "preference": None},
    }


def test_rejudge_adds_citation_verdicts_to_a_stored_run():
    itinerary = _itinerary((1, "Harbour cruise", ["S1"]), (2, "Night market", ["S3"]))
    client = FakeClient([_check(1, "S1", True, "harbour cruise"), _check(2, "S3", False)])
    judged = rejudge_record(_record(itinerary), Judge(client), kinds=("citation",))
    stored = judged["judge"]["citation"]
    assert stored["prompt"] == "citation" and stored["version"] == 1 and stored["had_context"] is True
    assert list(stored["cited_blocks"]) == ["S1", "S3"]
    pricing = Pricing.model_validate({"date": "2026-10-25", "currency": "USD", "embedding_chars_per_token": 4,
                                      "models": {"judge": {"input": 0.1, "output": 0.5}}})
    metrics = rejudged_metrics([judged], ("citation",), "judge", pricing)
    assert metrics["citation"]["supported_share"] == 0.5
    assert metrics["citation"]["by_corpus_coverage"]["city"]["citations"] == 2
