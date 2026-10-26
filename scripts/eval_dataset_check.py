"""
Check the evaluation dataset (eval/dataset.jsonl) for format and coverage problems.

Usage:
    python scripts/eval_dataset_check.py

Exits 0 when the dataset loads and passes the coverage check, 1 otherwise.
Needs no database and no API key.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from evaluation.dataset import DatasetError, check_dataset, load_dataset, load_meta  # noqa: E402


def main() -> int:
    try:
        entries = load_dataset()
        meta = load_meta()
    except DatasetError as exc:
        print(f"ERROR: {exc}")
        return 1

    problems = check_dataset(entries, meta)
    print(
        f"dataset v{meta.dataset_version}, corpus {meta.corpus_version}: "
        f"{len(entries)} entries"
    )
    for problem in problems:
        print(f"  FAIL {problem}")
    if problems:
        print(f"{len(problems)} problem(s) found")
        return 1
    print("coverage check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
