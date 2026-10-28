"""
Judge calibration (task 6.2): sample judged items for manual review, then score agreement.

Usage:
    python scripts/eval_calibration.py sample <run id> [--n 20] [--seed 0]
    python scripts/eval_calibration.py review <run id>
    python scripts/eval_calibration.py score <run id>

Files under eval/calibration/ (see docs/evaluation.md, "Judge calibration"):
  <run id>.review.md  the review sheet: every sampled item with its context and an answer
                      slot; replace each `?` with y / n
  <run id>.jsonl      the stored record: the judge's verdicts on the sampled items and the
                      reviewer's answers, one line per itinerary

`sample` draws the stratified sample and writes both files. `review` rebuilds the review
sheet from the .jsonl, keeping answers already recorded. `score` copies the answers from
the review sheet into the .jsonl and prints the agreement per stratum.
"""

import argparse
import json
import os
import random
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from evaluation.calibration import (  # noqa: E402
    MIN_AGREEMENT,
    MIN_SAMPLE,
    ItineraryScore,
    agreement,
    destination_only_template,
    load_scores,
    parse_review,
    render_review,
    stratified_template,
    unreviewed_items,
)
from evaluation.dataset import ROOT_DIR as REPO_ROOT  # noqa: E402
from evaluation.runner import RUNS_DIR  # noqa: E402

CALIBRATION_DIR = REPO_ROOT / "eval" / "calibration"


def run_records(run_id: str) -> dict[str, dict]:
    path = RUNS_DIR / run_id / "results.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["entry_id"]: r for r in records if r["judge"]["faithfulness"] and r["judge"]["destination"]}


def write_scores(run_id: str, scores: list[ItineraryScore]) -> None:
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    with (CALIBRATION_DIR / f"{run_id}.jsonl").open("w", encoding="utf-8") as handle:
        for score in scores:
            handle.write(json.dumps(score.model_dump(), ensure_ascii=False) + "\n")


def write_review(run_id: str, scores: list[ItineraryScore], records: dict[str, dict]) -> None:
    (CALIBRATION_DIR / f"{run_id}.review.md").write_text(render_review(run_id, scores, records),
                                                        encoding="utf-8")


def sample(run_id: str, n: int, seed: int) -> int:
    records = run_records(run_id)
    if len(records) < n:
        print(f"ERROR: run {run_id} has only {len(records)} judged itineraries, need {n}")
        return 1
    if (CALIBRATION_DIR / f"{run_id}.jsonl").exists():
        print(f"ERROR: eval/calibration/{run_id}.jsonl already exists; delete it first to resample")
        return 1

    rng = random.Random(seed)
    chosen = sorted(rng.sample(sorted(records.values(), key=lambda r: r["entry_id"]), n),
                    key=lambda r: r["entry_id"])
    scores = [stratified_template(r["entry_id"], r["judge"]["faithfulness"]["verdict"],
                                  r["judge"]["destination"]["verdict"], rng) for r in chosen]
    chosen_ids = {r["entry_id"] for r in chosen}
    scores += [destination_only_template(entry_id, r["judge"]["destination"]["verdict"])
               for entry_id, r in sorted(records.items())
               if entry_id not in chosen_ids
               and any(not p["in_destination"] for p in r["judge"]["destination"]["verdict"]["places"])]
    write_scores(run_id, scores)
    write_review(run_id, scores, records)
    claims = sum(len(s.claims) for s in scores)
    places = sum(len(s.places) for s in scores)
    print(f"wrote eval/calibration/{run_id}.review.md and .jsonl: {n} itineraries "
          f"(+{len(scores) - n} destination only), {claims} claims and {places} places to review")
    return 0


def review(run_id: str) -> int:
    scores = load_scores(CALIBRATION_DIR / f"{run_id}.jsonl")
    write_review(run_id, scores, run_records(run_id))
    print(f"wrote eval/calibration/{run_id}.review.md; recorded answers carried over, "
          f"{len(unreviewed_items(scores))} items still open")
    return 0


def score(run_id: str) -> int:
    jsonl = CALIBRATION_DIR / f"{run_id}.jsonl"
    sheet = CALIBRATION_DIR / f"{run_id}.review.md"
    try:
        scores = load_scores(jsonl)
        if sheet.exists():
            scores = parse_review(sheet.read_text(encoding="utf-8"), scores)
            write_scores(run_id, scores)
        open_items = unreviewed_items(scores)
        if open_items:
            print(f"{len(open_items)} item(s) still open, e.g. {', '.join(open_items[:5])}")
            return 1
        result = agreement(scores)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    if not result["sample_meets_minimum"]:
        print(f"WARNING: fewer than {MIN_SAMPLE} itineraries scored")
    low = [f"{group}.{name}" for group in ("faithfulness", "destination")
           for name, stratum in result[group].items()
           if stratum["agreement"] is not None and stratum["agreement"] < MIN_AGREEMENT]
    if low:
        print(f"WARNING: agreement below {MIN_AGREEMENT} for {', '.join(low)}: "
              "improve the judge prompt before relying on those numbers")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_sample = sub.add_parser("sample")
    p_sample.add_argument("run_id")
    p_sample.add_argument("--n", type=int, default=MIN_SAMPLE)
    p_sample.add_argument("--seed", type=int, default=0)
    for name in ("review", "score"):
        sub.add_parser(name).add_argument("run_id")
    args = parser.parse_args()
    if args.command == "sample":
        return sample(args.run_id, args.n, args.seed)
    return review(args.run_id) if args.command == "review" else score(args.run_id)


if __name__ == "__main__":
    sys.exit(main())
