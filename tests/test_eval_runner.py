"""build-evaluation-harness: the run loop, with every external service faked."""

import json
from types import SimpleNamespace

import pytest

from app.workflow.retrieval_service import RetrievedChunk
from evaluation.cost import Pricing
from evaluation.dataset import DatasetEntry
from evaluation.judge import Claim, DestinationVerdict, FaithfulnessVerdict, Judge, PlaceCheck
from evaluation.runner import (
    RunConfig,
    Services,
    load_config,
    load_subset,
    make_run_id,
    result_record,
    retry,
    run,
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
                                      "estimated_cost_aud": 50} for d in range(1, days + 1)],
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
        retrieve=lambda q: [RetrievedChunk(destination="Sydney", title="Guide to Sydney", chunk_text="x")],
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
    services.retrieve = lambda q: (_ for _ in ()).throw(RuntimeError("pgvector down"))
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
    assert metrics["cost"]["judge_calls"] == 4
    assert metrics["cost"]["price_table_date"] == "2026-10-25"


def test_result_record_keeps_judge_inputs_not_the_rendered_prompt():
    services, _ = _services([(200, _sse("s1", 2, with_rag=True))])
    record = result_record(run([_entry("e1")], CONFIG, services, PRICING)[0])

    faith = record["judge"]["faithfulness"]
    assert (faith["prompt"], faith["version"]) == ("faithfulness", 1)
    assert "[Guide to Sydney]" in faith["knowledge_context"]
    assert faith["itinerary_text"].startswith("Day 1")
    assert "Extract every specific claim" not in json.dumps(record)  # template text is not repeated
    assert record["outcome"]["events"][-1]["step"] == "validate_output"
    json.dumps(record)  # serialisable


def test_prompt_copies_written_once_per_run(tmp_path):
    judge = Judge(FakeJudgeClient())
    write_prompt_copies(tmp_path, judge)
    assert sorted(p.name for p in (tmp_path / "judge_prompts").iterdir()) == ["destination_v1.md",
                                                                              "faithfulness_v1.md"]


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
