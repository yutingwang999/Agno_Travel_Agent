"""
Regression gate: run the smoke subset and fail when a gated metric is out of bounds.

Usage:
    python scripts/eval_gate.py                    # run the smoke subset, then check it
    python scripts/eval_gate.py --run <run id>     # check an existing run
    python scripts/eval_gate.py --thresholds <file> ...

Exit status: 0 = pass, 1 = a metric is out of bounds (each failing metric is
named), 2 = the gate could not be evaluated (thresholds not set, run failed).
Thresholds live in eval/thresholds.yaml; record every change to them in the
"Threshold change log" of docs/experiments.md.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from evaluation.compare import load_summary  # noqa: E402
from evaluation.gate import THRESHOLDS_PATH, ThresholdsNotSet, check, load_thresholds  # noqa: E402
from evaluation.runner import RUNS_DIR  # noqa: E402


def run_smoke(config: str, subset: str) -> str:
    """Run eval_run.py and return the id of the run it wrote."""
    before = set(os.listdir(RUNS_DIR)) if RUNS_DIR.exists() else set()
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT_DIR, "scripts", "eval_run.py"), "--config", config, "--subset", subset],
        cwd=ROOT_DIR,
    )
    new = sorted(set(os.listdir(RUNS_DIR)) - before) if RUNS_DIR.exists() else []
    if result.returncode != 0 or len(new) != 1:
        sys.exit(f"GATE ERROR: the {subset} run did not complete (exit {result.returncode})")
    return new[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", help="check this existing run instead of running the smoke subset")
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    args = parser.parse_args()

    thresholds = load_thresholds(args.thresholds)
    run_id = args.run or run_smoke(thresholds.config, thresholds.subset)
    try:
        failures = check(load_summary(run_id), thresholds)
    except ThresholdsNotSet as exc:
        print(f"GATE ERROR: {exc}")
        return 2
    except FileNotFoundError as exc:
        print(f"GATE ERROR: {exc}")
        return 2

    if failures:
        print(f"GATE FAILED for run {run_id}:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"GATE PASSED for run {run_id} ({len(thresholds.metrics)} metrics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
