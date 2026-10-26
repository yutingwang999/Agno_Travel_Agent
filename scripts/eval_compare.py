"""
Print a Markdown table comparing several evaluation runs.

Usage:
    python scripts/eval_compare.py <run id> [<run id> ...]

Run ids are directory names under eval/runs/. Paste the output into the
"Records" section of docs/experiments.md.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from evaluation.compare import comparison_table, load_summary  # noqa: E402


def main(run_ids: list[str]) -> int:
    if not run_ids:
        print(__doc__.strip())
        return 1
    try:
        summaries = [load_summary(run_id) for run_id in run_ids]
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(comparison_table(summaries))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
