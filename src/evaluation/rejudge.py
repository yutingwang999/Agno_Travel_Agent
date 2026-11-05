"""Re-judge a stored run with the current judge prompts, without regenerating its itineraries.

Everything the judge needs is in the run's ``results.jsonl``: the request form, the
SSE events holding the itinerary, and the knowledge context the generator was given.
So before/after numbers can use the same prompts, and a new prompt version can be
applied to an old run.

Public API::

    from evaluation.rejudge import rejudge_records, rejudged_metrics
"""

from concurrent.futures import ThreadPoolExecutor

from evaluation.behaviour import describe_exception
from evaluation.cost import Pricing, token_cost
from evaluation.judge import (
    DestinationVerdict,
    FaithfulnessVerdict,
    Judge,
    PreferenceVerdict,
    destination_rate,
    faithfulness_by_coverage,
    faithfulness_summary,
    itinerary_text,
    preference_summary,
)
from evaluation.runner import judge_call_record, retry

KINDS = ("faithfulness", "destination", "preference")


def stored_itinerary(record: dict) -> dict:
    """The itinerary of a judged record, taken from its final SSE event."""
    final = next(e for e in record["outcome"]["events"] if e.get("step") == "validate_output")
    return final["data"]["itinerary"]


def rejudge_record(record: dict, judge: Judge, kinds: tuple[str, ...] = KINDS) -> dict:
    """Return *record* with the verdicts of *kinds* replaced; others are kept as stored.

    A record the original run did not judge stays as it is. A judge failure is recorded
    in ``judge.error`` and leaves that record's stored verdicts out of the new numbers.
    """
    stored = record["judge"]
    if not stored.get("faithfulness"):
        return record
    itinerary = stored_itinerary(record)
    text = stored["faithfulness"]["itinerary_text"]
    if itinerary_text(itinerary) != text:
        raise ValueError(f"{record['entry_id']}: the stored itinerary does not match what the run judged")
    form = record["form"]
    context = stored["faithfulness"]["knowledge_context"]
    judged = dict(stored, error=None)
    try:
        if "faithfulness" in kinds:
            call, ms = _timed(lambda: judge.faithfulness(itinerary, context))
            judged["faithfulness"] = judge_call_record(
                "faithfulness", judge, call, ms, itinerary_text=text, knowledge_context=context, had_context=bool(context)
            )
        if "destination" in kinds:
            call, ms = _timed(
                lambda: judge.destination(itinerary, form["destination"], form["trip_length"], form.get("notes"))
            )
            judged["destination"] = judge_call_record(
                "destination", judge, call, ms, itinerary_text=text, destination=form["destination"],
                trip_length=form["trip_length"], notes=form.get("notes"),
            )
        if "preference" in kinds:
            call, ms = _timed(lambda: judge.preference(itinerary, form["travel_style"], form.get("notes")))
            judged["preference"] = judge_call_record(
                "preference", judge, call, ms, itinerary_text=text, travel_style=form["travel_style"],
                notes=form.get("notes"),
            )
    except Exception as exc:  # noqa: BLE001 - recorded, and the run goes on
        judged = dict(stored, error=describe_exception(exc), rejudge_failed=True)
    return {**record, "judge": judged}


def _timed(call) -> tuple:
    import time

    start = time.perf_counter()
    result = retry(call)
    return result, (time.perf_counter() - start) * 1000


def rejudge_records(records: list[dict], judge: Judge, kinds: tuple[str, ...] = KINDS, concurrency: int = 4) -> list[dict]:
    """Re-judge every record concurrently, keeping their order."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda record: rejudge_record(record, judge, kinds), records))


def rejudged_metrics(records: list[dict], kinds: tuple[str, ...], judge_model: str, pricing: Pricing) -> dict:
    """The metrics that come from the judge, computed from the re-judged records, and the cost of re-judging."""
    usable = [r for r in records if r["judge"].get("faithfulness") and not r["judge"].get("rejudge_failed")]
    metrics: dict = {}
    if "faithfulness" in kinds:
        pairs = [
            (FaithfulnessVerdict.model_validate(r["judge"]["faithfulness"]["verdict"]), r["judge"]["faithfulness"]["had_context"])
            for r in usable
        ]
        covered = [
            (FaithfulnessVerdict.model_validate(r["judge"]["faithfulness"]["verdict"]), r["corpus_coverage"])
            for r in usable
            if r.get("corpus_coverage")
        ]
        metrics["faithfulness"] = {**faithfulness_summary(pairs), "by_corpus_coverage": faithfulness_by_coverage(covered)}
    if "destination" in kinds:
        verdicts = [DestinationVerdict.model_validate(r["judge"]["destination"]["verdict"]) for r in usable]
        metrics["destination"] = {"destination_rate": destination_rate(verdicts), "destination_judged": len(verdicts)}
    if "preference" in kinds:
        metrics["preference"] = preference_summary(
            [PreferenceVerdict.model_validate(r["judge"]["preference"]["verdict"]) for r in usable]
        )
    usage = [(r["judge"][kind]["input_tokens"], r["judge"][kind]["output_tokens"]) for r in usable for kind in kinds]
    metrics["rejudge"] = {
        "judged": len(usable),
        "judge_errors": sum(1 for r in records if r["judge"].get("rejudge_failed")),
        "cost_usd": sum(token_cost(judge_model, i, o, pricing) for i, o in usage),
    }
    return metrics
