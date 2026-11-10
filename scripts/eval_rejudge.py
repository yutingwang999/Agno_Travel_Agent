"""
Re-judge a stored evaluation run with the current judge prompts, without regenerating anything.

Usage:
    python scripts/eval_rejudge.py <run id> [--kinds faithfulness,destination,preference,citation] [--entries e001,e002]

Writes a new run directory, eval/runs/<UTC time>-<source config>-rejudge[-entries], with the
source's records and the new verdicts. Its summary is the source's, with the judge's metrics
replaced and `rejudged_from` naming the source. `--kinds` defaults to the first three;
`citation` (citation accuracy) is asked for explicitly. Each record gets the entry's
`corpus_coverage` from the dataset, so the judge's metrics can be split by it. See docs/evaluation.md.
"""

import argparse
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("--kinds", default="faithfulness,destination,preference")
    parser.add_argument("--entries", help="comma-separated entry ids, for checking a prompt by hand")
    args = parser.parse_args()

    load_dotenv(os.path.join(ROOT_DIR, ".env"), override=False)
    from evaluation.cost import load_pricing
    from evaluation.dataset import load_dataset
    from evaluation.judge import Judge
    from evaluation.rejudge import KINDS, rejudge_records, rejudged_metrics
    from evaluation.runner import RUNS_DIR, append_jsonl, git_state, make_run_id, utc_now, write_prompt_copies

    kinds = tuple(kind.strip() for kind in args.kinds.split(",") if kind.strip())
    unknown = set(kinds) - set(KINDS)
    if unknown:
        sys.exit(f"ERROR: unknown judge kinds {sorted(unknown)}; choose from {KINDS}")
    source_dir = RUNS_DIR / args.run_id
    results = source_dir / "results.jsonl"
    if not results.exists():
        sys.exit(f"ERROR: {results} not found; re-judging needs the run's local results.jsonl")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY not set")

    source = json.loads((source_dir / "summary.json").read_text(encoding="utf-8"))
    config = source["conditions"]["config"]
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines() if line.strip()]
    coverage = {entry.id: entry.corpus_coverage for entry in load_dataset()}
    records = [{**record, "corpus_coverage": coverage.get(record["entry_id"])} for record in records]
    if args.entries:
        wanted = {entry.strip() for entry in args.entries.split(",")}
        records = [record for record in records if record["entry_id"] in wanted]
        missing = wanted - {record["entry_id"] for record in records}
        if missing:
            sys.exit(f"ERROR: entries not in the run: {sorted(missing)}")

    os.environ["JUDGE_MODEL"] = config["judge_model"]
    judge = Judge.from_env()
    pricing = load_pricing()
    commit, dirty = git_state()
    started = utc_now()
    run_id = make_run_id(config["name"], "rejudge-entries" if args.entries else "rejudge", started)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    print(f"run {run_id}: re-judging {args.run_id} ({len(records)} records, {', '.join(kinds)}), "
          f"git {commit[:7]}{' (dirty)' if dirty else ''}", flush=True)

    judged = rejudge_records(records, judge, kinds, concurrency=config.get("judge_concurrency", 4))
    for record in judged:
        append_jsonl(run_dir / "results.jsonl", record)
    write_prompt_copies(run_dir, judge)
    fresh = rejudged_metrics(judged, kinds, judge.model, pricing)
    finished = utc_now()

    metrics = dict(source["metrics"])
    if "faithfulness" in fresh:
        metrics["faithfulness"] = {**fresh["faithfulness"], "judge_errors": fresh["rejudge"]["judge_errors"]}
    if "destination" in fresh:
        metrics["constraints"] = {**metrics.get("constraints", {}), **fresh["destination"]}
    if "preference" in fresh:
        metrics["preference"] = fresh["preference"]
    if "citation" in fresh:
        metrics["citation"] = fresh["citation"]
    metrics["rejudge"] = fresh["rejudge"]
    summary = {
        **source,
        "run_id": run_id,
        "rejudged_from": args.run_id,
        "rejudged_kinds": list(kinds),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "phase_seconds": {"total": round((finished - started).total_seconds(), 2)},
        "conditions": {**source["conditions"], "judge_prompts": judge.prompt_versions,
                       "judge_model": judge.model, "git_commit": commit, "git_dirty": dirty,
                       "source_git_commit": source["conditions"].get("git_commit")},
        "metrics": metrics,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: fresh[key] for key in fresh}, indent=2, ensure_ascii=False))
    print(f"wrote {run_dir}")
    return 1 if fresh["rejudge"]["judge_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
