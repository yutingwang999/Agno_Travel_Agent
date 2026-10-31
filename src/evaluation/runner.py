"""Evaluation run: send every entry to the system, score it, and write the run directory.

``scripts/eval_run.py`` wires the real services (in-process app, retrieval, trace
table, judge); this module holds the run logic with those services injected, so it
can be tested without a database or API key.

A run directory ``eval/runs/<run id>/`` holds (design decision 27):

- ``results.jsonl`` — one line per entry
- ``summary.json``  — run conditions and every metric
- ``judge_prompts/`` — a copy of each judge prompt file the run used
- ``generation_prompts/`` — the text of each prompt template version the run used
  (written by ``scripts/eval_run.py`` from the database; see :mod:`evaluation.templates`)

Requests to the system are sent one at a time; judge calls run concurrently
(design decision 28) and are retried with backoff, requests are not.
"""

import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, ConfigDict, Field

from evaluation.behaviour import Outcome, behaviour_correctness, describe_exception, observe
from evaluation.cost import Pricing, RequestCost, request_cost, summarize_costs
from evaluation.dataset import ROOT_DIR, DatasetEntry
from evaluation.judge import (
    DestinationVerdict,
    FaithfulnessVerdict,
    Judge,
    destination_rate,
    faithfulness_summary,
    itinerary_text,
    knowledge_context,
)
from evaluation.metrics import constraint_rates, system_metrics
from evaluation.retrieval import RetrievalResult, evaluate_entry, summarize

CONFIGS_DIR = ROOT_DIR / "eval" / "configs"
SUBSETS_DIR = ROOT_DIR / "eval" / "subsets"
RUNS_DIR = ROOT_DIR / "eval" / "runs"
# Paths whose changes do not make a run "dirty": run output and manual scores.
_UNTRACKED_OUTPUT = (":!eval/runs", ":!eval/calibration")

JUDGE_ATTEMPTS = 4
JUDGE_BACKOFF_SECONDS = 2.0


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    generation_model: str
    embedding_model: str
    judge_model: str
    corpus_version: str
    knowledge_table: str
    retrieval_k: int = Field(default=5, ge=1)
    judge_concurrency: int = Field(default=4, ge=1)
    request_parser: bool = False


def load_config(name: str, configs_dir: Path = CONFIGS_DIR) -> RunConfig:
    return RunConfig.model_validate(yaml.safe_load((configs_dir / f"{name}.yaml").read_text(encoding="utf-8")))


def load_subset(name: str, subsets_dir: Path = SUBSETS_DIR) -> list[str]:
    lines = (subsets_dir / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def select_entries(entries: list[DatasetEntry], ids: list[str] | None) -> list[DatasetEntry]:
    if ids is None:
        return entries
    by_id = {entry.id: entry for entry in entries}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"entries not in the dataset: {missing}")
    return [by_id[i] for i in ids]


def git_state(root: Path = ROOT_DIR) -> tuple[str, bool]:
    """Current commit and whether tracked or untracked files differ from it (run output excluded)."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                            check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--", ".", *_UNTRACKED_OUTPUT],
                            cwd=root, capture_output=True, text=True, check=True).stdout
    return commit, bool(status.strip())


def make_run_id(config_name: str, subset: str | None, now: datetime) -> str:
    suffix = f"-{subset}" if subset else ""
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{config_name}{suffix}"


@dataclass
class Services:
    """Everything a run talks to; real implementations live in scripts/eval_run.py."""

    send: Callable[[dict], tuple[int, str]]
    query_text: Callable[[dict], str]
    retrieve: Callable[[str], list]
    trace_rows: Callable[[str], list[dict]]
    intent_text: Callable[[dict], str | None]
    judge: Judge | None


@dataclass
class EntryRun:
    entry: DatasetEntry
    outcome: Outcome
    retrieval: RetrievalResult | None = None
    retrieval_error: str | None = None
    retrieval_ms: float | None = None  # intake + intent matching + retrieval, harness-side
    cost: RequestCost | None = None
    trace_rows: list[dict] | None = None
    faithfulness: dict | None = None
    destination: dict | None = None
    judge_error: str | None = None


def retry(call: Callable, attempts: int = JUDGE_ATTEMPTS, backoff: float = JUDGE_BACKOFF_SECONDS,
          sleep: Callable[[float], None] = time.sleep):
    """Run *call*, retrying transient API failures with exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts or not _is_transient(exc):
                raise
            sleep(backoff * 2 ** (attempt - 1))


def _is_transient(exc: Exception) -> bool:
    try:
        import openai
    except ImportError:
        return False
    return isinstance(exc, (openai.RateLimitError, openai.APIConnectionError,
                            openai.APITimeoutError, openai.InternalServerError))


def run_entry(entry: DatasetEntry, config: RunConfig, services: Services, pricing: Pricing) -> EntryRun:
    """Send one entry and gather everything except the judge's verdicts."""
    form = entry.form.model_dump(exclude_none=True)
    result = EntryRun(entry=entry, outcome=observe(lambda: services.send(form)))

    if entry.relevant_sections:
        start = time.perf_counter()
        try:
            result.retrieval = evaluate_entry(entry, services.query_text, services.retrieve, config.retrieval_k)
        except Exception as exc:  # noqa: BLE001 — record it and keep going
            result.retrieval_error = describe_exception(exc)
        result.retrieval_ms = _elapsed_ms(start)

    session_id = next((e.get("session_id") for e in result.outcome.events), None)
    result.trace_rows = services.trace_rows(session_id) if session_id else []
    embedded = [text for text in (services.intent_text(form), _rag_query(result.outcome)) if text]
    result.cost = request_cost(result.trace_rows, embedded, config.generation_model,
                               config.embedding_model, pricing)
    return result


def judge_entry(result: EntryRun, judge: Judge) -> None:
    """Fill in the judge's verdicts for a planned itinerary (mutates *result*)."""
    itinerary = result.outcome.itinerary
    context = knowledge_context(result.outcome.events)
    try:
        start = time.perf_counter()
        faith = retry(lambda: judge.faithfulness(itinerary, context))
        faith_ms = _elapsed_ms(start)
        start = time.perf_counter()
        place = retry(lambda: judge.destination(itinerary, result.entry.form.destination,
                                                result.entry.form.trip_length))
        place_ms = _elapsed_ms(start)
    except Exception as exc:  # noqa: BLE001
        result.judge_error = describe_exception(exc)
        return
    text = itinerary_text(itinerary)
    result.faithfulness = {"prompt": "faithfulness", "version": judge.prompt_versions["faithfulness"],
                           "itinerary_text": text, "knowledge_context": context, "had_context": bool(context),
                           "verdict": faith.verdict.model_dump(), "model": judge.model,
                           "input_tokens": faith.input_tokens, "output_tokens": faith.output_tokens,
                           "latency_ms": faith_ms}
    result.destination = {"prompt": "destination", "version": judge.prompt_versions["destination"],
                          "itinerary_text": text, "destination": result.entry.form.destination,
                          "trip_length": result.entry.form.trip_length,
                          "verdict": place.verdict.model_dump(), "model": judge.model,
                          "input_tokens": place.input_tokens, "output_tokens": place.output_tokens,
                          "latency_ms": place_ms}


def run(entries: list[DatasetEntry], config: RunConfig, services: Services, pricing: Pricing,
        on_result: Callable[[EntryRun], None] = lambda r: None,
        phase_seconds: dict | None = None) -> list[EntryRun]:
    """Send entries one by one, then judge planned itineraries concurrently.

    When *phase_seconds* is given, it is filled with the wall-clock time of each
    phase (see :func:`phase_breakdown`).
    """
    start = time.perf_counter()
    results = [run_entry(entry, config, services, pricing) for entry in entries]
    sending = time.perf_counter() - start

    start = time.perf_counter()
    planned = [r for r in results if r.outcome.behaviour == "plan" and r.outcome.itinerary is not None]
    if services.judge is not None and planned:
        with ThreadPoolExecutor(max_workers=config.judge_concurrency) as pool:
            list(pool.map(lambda r: judge_entry(r, services.judge), planned))
    judging = time.perf_counter() - start

    for result in results:
        on_result(result)
    if phase_seconds is not None:
        phase_seconds.update(phase_breakdown(results, sending, judging))
    return results


def phase_breakdown(results: list[EntryRun], sending_seconds: float, judging_seconds: float) -> dict:
    """Where a run's time went, in seconds.

    The sequential phase is split into the requests to the system, the harness's
    own retrieval measurement, and the rest (trace reads, cost); the judge phase is
    wall-clock time with calls running concurrently, so it is less than the sum of
    the individual judge call latencies, which is reported beside it.
    """
    requests = sum(r.outcome.latency_ms or 0 for r in results) / 1000
    retrieval = sum(r.retrieval_ms or 0 for r in results) / 1000
    judge_calls = sum(d["latency_ms"] for r in results for d in (r.faithfulness, r.destination) if d) / 1000
    return {
        "requests": round(requests, 2),
        "retrieval_measurement": round(retrieval, 2),
        "other_sequential": round(max(sending_seconds - requests - retrieval, 0.0), 2),
        "judge_wall": round(judging_seconds, 2),
        "judge_calls_sum": round(judge_calls, 2),
    }


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def result_record(result: EntryRun) -> dict:
    """The results.jsonl line for one entry."""
    outcome = result.outcome
    return {
        "entry_id": result.entry.id,
        "tags": result.entry.tags,
        "expected_behavior": result.entry.expected_behavior,
        "form": result.entry.form.model_dump(exclude_none=True),
        "outcome": {
            "behaviour": outcome.behaviour,
            "status_code": outcome.status_code,
            "reason": outcome.reason,
            "error": outcome.error,
            "latency_ms": outcome.latency_ms,
            "events": outcome.events,
        },
        "retrieval": ({**asdict(result.retrieval), "latency_ms": result.retrieval_ms}
                      if result.retrieval else None),
        "retrieval_error": result.retrieval_error,
        "trace_rows": result.trace_rows,
        "cost": {**asdict(result.cost), "total_usd": result.cost.total_usd} if result.cost else None,
        "judge": {"faithfulness": result.faithfulness, "destination": result.destination,
                  "error": result.judge_error},
    }


STEP_ORDER = ("intake", "cag_match", "retrieval_decision", "rag_retrieve", "generate", "validate_output")


def step_latencies(results: list[EntryRun]) -> dict:
    """Mean latency of each workflow step, from the latency every step writes to its trace row.

    ``runs`` is how many requests ran the step (rag_retrieve only runs on the
    retrieval path), so each mean is over the requests that ran it.
    """
    samples: dict[str, list[float]] = {}
    for result in results:
        for row in result.trace_rows or []:
            if row.get("latency_ms") is not None:
                samples.setdefault(row["step_name"], []).append(row["latency_ms"])
    ordered = [s for s in STEP_ORDER if s in samples] + sorted(set(samples) - set(STEP_ORDER))
    return {step: {"runs": len(samples[step]), "mean_ms": round(sum(samples[step]) / len(samples[step]), 1)}
            for step in ordered}


def _rag_query(outcome: Outcome) -> str | None:
    """The query rag_retrieve embedded, when retrieval ran."""
    event = next((e for e in outcome.events if e.get("step") == "rag_retrieve"), None)
    return (event or {}).get("data", {}).get("query_text")


def summarise(results: list[EntryRun], config: RunConfig, pricing: Pricing) -> dict:
    """Run conditions that need the results, plus every metric."""
    pairs = [(r.entry, r.outcome) for r in results]
    retrieval_results = [r.retrieval for r in results if r.retrieval]
    faith = [(FaithfulnessVerdict.model_validate(r.faithfulness["verdict"]), r.faithfulness["had_context"])
             for r in results if r.faithfulness]
    places = [DestinationVerdict.model_validate(r.destination["verdict"]) for r in results if r.destination]
    judge_usage = [(d["input_tokens"], d["output_tokens"])
                   for r in results for d in (r.faithfulness, r.destination) if d]
    templates = sorted({(e["data"]["prompt_template_key"], e["data"]["prompt_template_version"])
                        for r in results for e in r.outcome.events
                        if e.get("step") == "generate" and e.get("status") == "completed"})

    constraints = constraint_rates(pairs)
    constraints["destination_rate"] = destination_rate(places)
    constraints["destination_judged"] = len(places)
    return {
        "generation_templates": [{"key": k, "version": v} for k, v in templates],
        "metrics": {
            "slot_extraction": ({"value": None, "reason": "no request parser"}
                                if not config.request_parser else {"value": None, "reason": "not implemented"}),
            "retrieval": {**summarize(retrieval_results, config.retrieval_k),
                          "errors": sum(1 for r in results if r.retrieval_error)},
            "behaviour": behaviour_correctness(pairs),
            "constraints": constraints,
            "faithfulness": {**faithfulness_summary(faith),
                             "judge_errors": sum(1 for r in results if r.judge_error)},
            "system": {**system_metrics([r.outcome for r in results]),
                       "step_latency_ms": step_latencies(results)},
            "cost": summarize_costs([r.cost for r in results if r.cost], judge_usage,
                                    config.judge_model, pricing),
        },
    }


def write_prompt_copies(run_dir: Path, judge: Judge | None) -> None:
    if judge is None:
        return
    target = run_dir / "judge_prompts"
    target.mkdir(parents=True, exist_ok=True)
    for name, version in judge.prompt_versions.items():
        shutil.copyfile(judge.prompts_dir / f"{name}_v{version}.md", target / f"{name}_v{version}.md")


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
