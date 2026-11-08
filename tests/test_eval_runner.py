"""build-evaluation-harness: the run loop, with every external service faked."""

import json
from types import SimpleNamespace

import pytest

from app.workflow.retrieval_service import RetrievedChunk
from evaluation.cost import Pricing
from evaluation.dataset import DatasetEntry
from evaluation.judge import (
    Claim,
    DestinationVerdict,
    FaithfulnessVerdict,
    Judge,
    PlaceCheck,
    PreferenceCheck,
    PreferenceVerdict,
)
from evaluation.runner import (
    RunConfig,
    Services,
    load_config,
    load_subset,
    make_run_id,
    result_record,
    retry,
    run,
    run_retrieval_only,
    select_entries,
    summarise,
    write_prompt_copies,
)

CONFIG = RunConfig(name="t", generation_model="gen", embedding_model="emb", judge_model="judge",
                   corpus_version="v1", knowledge_table="travel_docs_v1", judge_concurrency=2)
PRICING = Pricing.model_validate({
    "date": "2026-10-25", "currency": "USD", "embedding_chars_per_token": 4,
    "models": {"gen": {"input": 0.25, "output": 1.5}, "emb": {"input": 0.15},
               "judge": {"input": 0.1, "output": 0.5}},
})


def _entry(entry_id, expected="plan", sections=("Guide to Sydney",), days=2, tags=()):
    return DatasetEntry.model_validate({
        "id": entry_id, "tags": list(tags),
        "form": {"destination": "Sydney", "trip_length": days, "budget": "budget", "travel_style": "family"},
        "utterance": "...", "gold_slots": {"destination": "sydney", "trip_length_days": days},
        "expected_behavior": expected,
        "relevant_sections": [{"source": "handwritten", "section": s} for s in sections],
        "needs_knowledge": bool(sections),
    })


def _sse(session_id, days, with_rag):
    itinerary = {"daily_itinerary": [{"day": d, "morning": "m", "afternoon": "a", "evening": "e",
                                      "estimated_cost_aud": 50, "sources": []} for d in range(1, days + 1)],
                 "total_estimated_cost_aud": 50 * days, "key_tips": ["t"]}
    events = [{"session_id": session_id, "step": "intake", "status": "completed", "data": {}}]
    if with_rag:
        events.append({"session_id": session_id, "step": "rag_retrieve", "status": "completed",
                       "data": {"query_text": "family travel in sydney",
                                "retrieved_context": [{"title": "Guide to Sydney", "chunk_text": "Bondi"}]}})
    events += [
        {"session_id": session_id, "step": "generate", "status": "completed",
         "data": {"raw_llm_output": "{}", "prompt_template_key": "low_confidence_with_retrieval",
                  "prompt_template_version": 1}},
        {"session_id": session_id, "step": "validate_output", "status": "completed",
         "data": {"itinerary": itinerary, "degraded_mode": False}},
    ]
    return "".join(f"data: {json.dumps(e)}\r\n\r\n" for e in events)


class FakeJudgeClient:
    def __init__(self):
        self.responses = SimpleNamespace(parse=self.parse)

    def parse(self, model, input, text_format):
        verdict = (FaithfulnessVerdict(claims=[Claim(category="named_place", text="Bondi", supported=True)])
                   if text_format is FaithfulnessVerdict
                   else PreferenceVerdict(preferences=[PreferenceCheck(preference="beach", followed=True, reason="r")],
                                          added_requirements=[])
                   if text_format is PreferenceVerdict
                   else DestinationVerdict(places=[PlaceCheck(name="Bondi", in_destination=True, reason="r")]))
        return SimpleNamespace(output_parsed=verdict, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def _services(responses):
    sent = []

    def send(form):
        sent.append(form)
        status, body = responses.pop(0)
        if isinstance(body, Exception):
            raise body
        return status, body

    services = Services(
        send=send,
        query_text=lambda form: "family travel in sydney",
        retrieve=lambda q, form: [RetrievedChunk(destination="Sydney", title="Guide to Sydney", chunk_text="x")],
        trace_rows=lambda sid: [{"step_name": "generate", "status": "completed",
                                 "input_tokens": 1000, "output_tokens": 500}],
        intent_text=lambda form: "family trip to sydney with budget budget",
        judge=Judge(FakeJudgeClient(), model="judge"),
    )
    return services, sent


def test_run_scores_every_entry_and_survives_a_failure():
    entries = [_entry("e1"), _entry("e2", expected="refuse", sections=(), tags=["out_of_scope"]),
               _entry("e3", sections=())]
    services, sent = _services([
        (200, _sse("s1", 2, with_rag=True)),
        (200, ConnectionError("boom")),
        (422, json.dumps({"reason": "destination_out_of_scope", "detail": "..."})),
    ])
    written = []
    results = run(entries, CONFIG, services, PRICING, on_result=written.append)

    assert [r.outcome.behaviour for r in results] == ["plan", "error", "refuse"]
    assert "ConnectionError: boom" in results[1].outcome.error
    assert len(written) == 3 and len(sent) == 3
    # retrieval only for labelled entries; judge only for planned itineraries
    assert results[0].retrieval.recall == 1.0 and results[2].retrieval is None
    assert results[0].faithfulness["had_context"] is True
    assert results[0].faithfulness["verdict"]["claims"][0]["supported"] is True
    assert results[1].faithfulness is None and results[2].destination is None
    # cost: generation from trace tokens, embedding from intent + rag query
    assert results[0].cost.generation_usd == pytest.approx((1000 * 0.25 + 500 * 1.5) / 1e6)
    assert results[0].cost.embedding_usd > 0


def test_phase_seconds_and_per_call_latency_are_recorded():
    services, _ = _services([(200, _sse("s1", 2, with_rag=True))])
    phases = {}
    result = run([_entry("e1")], CONFIG, services, PRICING, phase_seconds=phases)[0]

    assert set(phases) == {"requests", "retrieval_measurement", "other_sequential",
                           "judge_wall", "judge_calls_sum"}
    assert all(value >= 0 for value in phases.values())
    assert result.retrieval_ms is not None
    assert result.faithfulness["latency_ms"] >= 0 and result.destination["latency_ms"] >= 0
    record = result_record(result)
    assert "latency_ms" in record["retrieval"]
    assert "latency_ms" in record["judge"]["faithfulness"]


def test_step_latencies_average_over_requests_that_ran_the_step():
    from evaluation.runner import EntryRun, step_latencies
    from evaluation.behaviour import Outcome

    def entry_run(rows):
        return EntryRun(entry=_entry("e"), outcome=Outcome("plan"), trace_rows=rows)

    results = [
        entry_run([{"step_name": "generate", "latency_ms": 3000}, {"step_name": "rag_retrieve", "latency_ms": 600}]),
        entry_run([{"step_name": "generate", "latency_ms": 2000}, {"step_name": "intake", "latency_ms": None}]),
    ]
    assert step_latencies(results) == {
        "rag_retrieve": {"runs": 1, "mean_ms": 600.0},
        "generate": {"runs": 2, "mean_ms": 2500.0},
    }


def test_retrieval_error_is_recorded_not_raised():
    services, _ = _services([(200, _sse("s1", 2, with_rag=False))])
    services.retrieve = lambda q, form: (_ for _ in ()).throw(RuntimeError("pgvector down"))
    result = run([_entry("e1")], CONFIG, services, PRICING)[0]
    assert result.retrieval is None
    assert "pgvector down" in result.retrieval_error


def test_summary_has_every_metric_and_template():
    services, _ = _services([(200, _sse("s1", 2, with_rag=False)), (200, _sse("s2", 2, with_rag=True))])
    results = run([_entry("e1"), _entry("e2")], CONFIG, services, PRICING)
    summary = summarise(results, CONFIG, PRICING)
    metrics = summary["metrics"]

    assert summary["generation_templates"] == [{"key": "low_confidence_with_retrieval", "version": 1}]
    assert metrics["slot_extraction"] == {"value": None, "reason": "no request parser"}
    assert metrics["retrieval"]["recall_at_k"] == 1.0
    assert metrics["behaviour"]["overall"] == 1.0
    assert metrics["constraints"]["trip_length_rate"] == 1.0
    assert metrics["constraints"]["budget_rate"] == 1.0
    assert metrics["constraints"]["destination_rate"] == 1.0
    assert metrics["faithfulness"]["with_context"]["itineraries"] == 1
    assert metrics["faithfulness"]["without_context"]["itineraries"] == 1
    assert metrics["system"]["error_rate"] == 0.0
    assert metrics["cost"]["judge_calls"] == 6
    assert metrics["preference"]["followed_share"] == 1.0
    assert metrics["cost"]["price_table_date"] == "2026-10-25"


def test_result_record_keeps_judge_inputs_not_the_rendered_prompt():
    services, _ = _services([(200, _sse("s1", 2, with_rag=True))])
    record = result_record(run([_entry("e1")], CONFIG, services, PRICING)[0])

    faith = record["judge"]["faithfulness"]
    assert (faith["prompt"], faith["version"]) == ("faithfulness", 2)
    fit = record["judge"]["preference"]
    assert (fit["prompt"], fit["version"]) == ("preference", 4)
    assert fit["verdict"]["preferences"][0]["followed"] is True
    assert "[S1] Guide to Sydney" in faith["knowledge_context"]
    assert faith["itinerary_text"].startswith("Day 1")
    assert "Extract every specific claim" not in json.dumps(record)  # template text is not repeated
    assert record["outcome"]["events"][-1]["step"] == "validate_output"
    json.dumps(record)  # serialisable


def test_prompt_copies_written_once_per_run(tmp_path):
    judge = Judge(FakeJudgeClient())
    write_prompt_copies(tmp_path, judge)
    assert sorted(p.name for p in (tmp_path / "judge_prompts").iterdir()) == ["destination_v2.md",
                                                                              "faithfulness_v2.md",
                                                                              "preference_v4.md"]


def test_retry_only_transient_errors():
    import openai

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise openai.APIConnectionError(request=None)
        return "ok"

    assert retry(flaky, sleep=lambda s: None) == "ok" and len(calls) == 3

    with pytest.raises(ValueError):
        retry(lambda: (_ for _ in ()).throw(ValueError("bad schema")), sleep=lambda s: None)


def test_config_subset_and_selection():
    config = load_config("v010-baseline")
    assert config.generation_model == "gemini-3.1-flash-lite"
    assert config.knowledge_table == "travel_docs_v1"
    smoke = load_subset("smoke")
    assert len(smoke) == 10

    entries = [_entry("e1"), _entry("e2")]
    assert [e.id for e in select_entries(entries, ["e2"])] == ["e2"]
    with pytest.raises(ValueError, match="not in the dataset"):
        select_entries(entries, ["e9"])


def test_smoke_subset_ids_exist_in_dataset():
    from evaluation.dataset import load_dataset

    select_entries(load_dataset(), load_subset("smoke"))


def test_run_id_format():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 26, 9, 5, 0, tzinfo=timezone.utc)
    assert make_run_id("v010-baseline", "smoke", now) == "20261026T090500Z-v010-baseline-smoke"
    assert make_run_id("v010-baseline", None, now) == "20261026T090500Z-v010-baseline"


def test_budget_amount_is_sent_with_the_request():
    """Spec scenario "Amount sent with the request"; absent amounts are not sent."""
    with_amount = _entry("e1").model_copy(deep=True)
    with_amount.form.max_daily_budget_aud = 150
    services, sent = _services([(200, _sse("s1", 2, with_rag=True)), (200, _sse("s2", 2, with_rag=True))])
    run([with_amount, _entry("e2")], CONFIG, services, PRICING)

    assert sent[0]["max_daily_budget_aud"] == 150
    assert "max_daily_budget_aud" not in sent[1]


def _coverage_entry(entry_id, sections, coverage):
    return DatasetEntry.model_validate({
        "id": entry_id, "tags": [],
        "form": {"destination": "Sydney", "trip_length": 2, "budget": "budget", "travel_style": "family"},
        "utterance": "...", "gold_slots": {"destination": "sydney", "trip_length_days": 2},
        "expected_behavior": "plan",
        "relevant_sections": [{"source": "handwritten", "section": s} for s in sections],
        "corpus_coverage": coverage,
    })


def test_retrieval_only_measures_labelled_entries_without_sending_anything():
    entries = [
        _coverage_entry("e1", ["Hit"], "national_only"),
        _coverage_entry("e2", ["Miss"], "national_only"),
        _coverage_entry("e3", [], "none"),
    ]
    chunk = RetrievedChunk(destination="australia", title="Hit", chunk_text="...", metadata={})
    records = []

    metrics = run_retrieval_only(entries, CONFIG, lambda form: "query", lambda query, form: [chunk], records.append)

    retrieval = metrics["retrieval"]
    assert set(metrics) == {"retrieval"}
    assert retrieval["entries"] == 2  # coverage "none" takes no part
    assert retrieval["recall_at_k"] == pytest.approx(0.5)
    assert retrieval["by_corpus_coverage"]["national_only"]["entries"] == 2
    assert "none" not in retrieval["by_corpus_coverage"]
    assert retrieval["retrieve_latency_p50_ms"] >= 0
    assert [record["entry_id"] for record in records] == ["e1", "e2"]


def test_retrieval_only_records_an_error_instead_of_a_zero_recall():
    def failing(query, form):
        raise RuntimeError("database down")

    records = []
    metrics = run_retrieval_only([_coverage_entry("e1", ["Hit"], "national_only")], CONFIG,
                                 lambda form: "query", failing, records.append)

    assert metrics["retrieval"]["errors"] == 1
    assert metrics["retrieval"]["recall_at_k"] is None
    assert "retrieval_error" in records[0]


def test_query_comparison_configs_cover_every_query_construction():
    """The odd groups of the 12-group comparison; group 1 is step b, which ran before notes reached the query."""
    configs = [load_config("rebuild-rag-b")]
    configs += [load_config(f"rebuild-rag-q{number}") for number in (3, 5, 7, 9, 11)]

    groups = {(c.query_notes, c.query_category) for c in configs}

    assert groups == {
        (notes, category)
        for notes in (False, True)
        for category in ("matched", "no_budget", "no_category")
    }
    assert {c.knowledge_table for c in configs} == {"travel_docs_v2_c800"}
    assert all(c.destination_filter and c.retrieval_k == 5 for c in configs)


@pytest.mark.parametrize(
    ("fields", "differs"),
    [
        ({}, False),
        ({"query_notes": False}, True),
        ({"query_category": "matched"}, True),
        ({"query_category": "no_budget"}, True),
    ],
)
def test_a_query_the_workflow_does_not_send_is_flagged(fields, differs):
    assert CONFIG.model_copy(update=fields).query_differs_from_workflow is differs


@pytest.mark.parametrize("name", ["rebuild-rag-q11", "rebuild-rag-c500", "rebuild-rag-c1200", "rebuild-rag-c800-semantic"])
def test_chunking_configs_search_the_table_built_for_them(name):
    """A table must be searched with the task types it was embedded with."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("dev", Path(__file__).resolve().parents[1] / "scripts" / "dev.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)

    config = load_config(name)
    _, task_types, _ = dev.EVAL_KNOWLEDGE_TABLES[config.knowledge_table]
    assert config.embedding_task_types == task_types
    assert not config.query_differs_from_workflow



def test_template_version_defaults_to_the_active_version():
    assert CONFIG.template_version is None
    assert CONFIG.generate_params == {}
    assert CONFIG.model_copy(update={"template_version": 2}).generate_params == {"template_version": 2}


@pytest.mark.parametrize(("letter", "version"), [("a", 1), ("b", 2), ("c", 3)])
def test_generation_variant_configs_pin_their_template(letter, version):
    """Task 5.4: the three variants differ only in the template version they pin."""
    config = load_config(f"rebuild-rag-gen-{letter}")
    reference = load_config("rebuild-rag-q11")

    assert config.template_version == version
    assert not config.query_differs_from_workflow
    ignored = {"name", "description", "template_version"}
    assert config.model_dump(exclude=ignored) == reference.model_dump(exclude=ignored)

