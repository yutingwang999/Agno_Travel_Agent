"""Comparison table: several run summaries side by side, as Markdown.

One column per run, one row per run condition and per metric. A run made with
uncommitted changes (``git_dirty``) is marked ⚠️; such runs are for reference only
(docs/experiments.md, rule 2).

Public API::

    from evaluation.compare import comparison_table, load_summary

    print(comparison_table([load_summary(run_id) for run_id in run_ids]))
"""

import json
from pathlib import Path
from typing import Any, Callable

from evaluation.runner import RUNS_DIR

DIRTY_MARK = "⚠️"
MISSING = "—"


def load_summary(run_id: str, runs_dir: Path = RUNS_DIR) -> dict:
    path = runs_dir / run_id / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"no summary for run {run_id!r} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def get(summary: dict, path: str) -> Any:
    """Read a dotted path such as ``metrics.retrieval.recall_at_k``; None when absent."""
    value: Any = summary
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def percent(value) -> str:
    return MISSING if value is None else f"{value * 100:.1f}%"


def number(value, digits: int = 3) -> str:
    return MISSING if value is None else f"{value:.{digits}f}"


def seconds(value_ms) -> str:
    return MISSING if value_ms is None else f"{value_ms / 1000:.2f} s"


def usd(value) -> str:
    return MISSING if value is None else f"${value:.5f}"


def text(value) -> str:
    return MISSING if value in (None, "", [], {}) else str(value)


def _slot(summary: dict) -> str:
    slot = get(summary, "metrics.slot_extraction") or {}
    return percent(slot["value"]) if slot.get("value") is not None else f"N/A ({slot.get('reason', '?')})"


def _templates(summary: dict) -> str:
    items = get(summary, "conditions.generation_templates") or []
    return ", ".join(f"{t['key']} v{t['version']}" for t in items) or MISSING


def _correction_template(summary: dict) -> str:
    template = get(summary, "conditions.correction_template")
    return f"{template['key']} v{template['version']}" if template else MISSING


def _judge_prompts(summary: dict) -> str:
    prompts = get(summary, "conditions.judge_prompts") or {}
    return ", ".join(f"{name} v{version}" for name, version in prompts.items()) or MISSING


Row = tuple[str, Callable[[dict], str]]

CONDITION_ROWS: list[Row] = [
    ("git commit", lambda s: f"`{(get(s, 'conditions.git_commit') or '')[:7]}`"
                             + (f" {DIRTY_MARK} uncommitted" if get(s, "conditions.git_dirty") else "")),
    ("Subset / entries", lambda s: f"{text(get(s, 'subset'))} / {text(get(s, 'entries'))}"),
    ("Dataset version", lambda s: text(get(s, "conditions.dataset_version"))),
    ("Corpus version / knowledge table",
     lambda s: f"{text(get(s, 'conditions.corpus_version'))} / `{text(get(s, 'conditions.knowledge_table'))}`"),
    ("Generation model", lambda s: text(get(s, "conditions.generation_model"))),
    ("Generation templates", _templates),
    ("Correction template", _correction_template),
    ("Judge model / prompts", lambda s: f"{text(get(s, 'conditions.judge_model'))} ({_judge_prompts(s)})"),
    ("Price table date", lambda s: text(get(s, "conditions.price_table_date"))),
]

METRIC_ROWS: list[Row] = [
    ("Slot extraction accuracy", _slot),
    ("Recall@k", lambda s: number(get(s, "metrics.retrieval.recall_at_k"))),
    ("MRR@k", lambda s: number(get(s, "metrics.retrieval.mrr_at_k"))),
    ("Behaviour correctness", lambda s: percent(get(s, "metrics.behaviour.overall"))),
    ("Faithfulness (all)", lambda s: percent(get(s, "metrics.faithfulness.overall.supported_share"))),
    ("Faithfulness (with context)", lambda s: percent(get(s, "metrics.faithfulness.with_context.supported_share"))),
    ("Faithfulness (no context)",
     lambda s: percent(get(s, "metrics.faithfulness.without_context.supported_share"))),
    ("Trip length correct", lambda s: percent(get(s, "metrics.constraints.trip_length_rate"))),
    ("Within budget", lambda s: percent(get(s, "metrics.constraints.budget_rate"))),
    ("Attractions in destination", lambda s: percent(get(s, "metrics.constraints.destination_rate"))),
    ("Format pass rate", lambda s: percent(get(s, "metrics.system.format_pass_rate"))),
    ("Retry rate", lambda s: percent(get(s, "metrics.system.retry_rate"))),
    ("Error rate", lambda s: percent(get(s, "metrics.system.error_rate"))),
    ("Latency p50", lambda s: seconds(get(s, "metrics.system.latency_p50_ms"))),
    ("Latency p95", lambda s: seconds(get(s, "metrics.system.latency_p95_ms"))),
    ("Cost per request", lambda s: usd(get(s, "metrics.cost.mean_request_usd"))),
    ("Judge cost (total)", lambda s: usd(get(s, "metrics.cost.judge_total_usd"))),
]


def _step_rows(summaries: list[dict]) -> list[Row]:
    steps: list[str] = []
    for s in summaries:
        for step in get(s, "metrics.system.step_latency_ms") or {}:
            if step not in steps:
                steps.append(step)

    def render(s: dict, step: str) -> str:
        item = (get(s, "metrics.system.step_latency_ms") or {}).get(step)
        return MISSING if item is None else f"{item['mean_ms']:.0f} ms (n={item['runs']})"

    return [(f"Step latency: `{step}`", lambda s, step=step: render(s, step)) for step in steps]


def _tag_rows(summaries: list[dict]) -> list[Row]:
    tags = sorted({tag for s in summaries for tag in (get(s, "metrics.behaviour.by_tag") or {})})
    return [(f"Behaviour correctness: `{tag}`",
             lambda s, tag=tag: percent((get(s, "metrics.behaviour.by_tag") or {}).get(tag)))
            for tag in tags]


def comparison_table(summaries: list[dict]) -> str:
    """A Markdown table comparing *summaries*, one column each."""
    if not summaries:
        raise ValueError("need at least one run")
    headers = [("{} {}".format(DIRTY_MARK, s["run_id"]) if get(s, "conditions.git_dirty") else s["run_id"])
               for s in summaries]
    lines = ["| Item | " + " | ".join(f"`{h}`" if not h.startswith(DIRTY_MARK) else h for h in headers) + " |",
             "| --- |" + " --- |" * len(summaries)]
    for label, render in CONDITION_ROWS + METRIC_ROWS + _step_rows(summaries) + _tag_rows(summaries):
        lines.append(f"| {label} | " + " | ".join(render(s) for s in summaries) + " |")
    if any(get(s, "conditions.git_dirty") for s in summaries):
        lines.append("")
        lines.append(f"{DIRTY_MARK} Run made with uncommitted changes: for reference only, "
                     "not for formal comparison.")
    return "\n".join(lines)
