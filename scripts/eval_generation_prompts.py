"""
Add generation_prompts/ to a run made before eval_run.py wrote it.

Usage:
    python scripts/eval_generation_prompts.py <run id> --correction-version N

Reads the generation template versions from the run's summary.json and copies
their text, plus the given version of the correction template, from the
evaluation database (EVAL_DATABASE_URL) into eval/runs/<run id>/generation_prompts/.
Such runs do not record which correction template was active, so pass the
version that was active at the run's commit (ACTIVE_TEMPLATE_VERSIONS in
scripts/seed.py; every key was version 1 before harden-workflow-guardrails).
summary.json is not changed, and existing files are never overwritten.
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

from evaluation.runner import RUNS_DIR  # noqa: E402
from evaluation.templates import (  # noqa: E402
    CORRECTION_TEMPLATE_KEY,
    read_template_texts,
    templates_used,
    write_generation_prompts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("--correction-version", type=int, required=True,
                        help="version of validate_output_correction active when the run was made")
    args = parser.parse_args()

    load_dotenv(os.path.join(ROOT_DIR, ".env"), override=False)
    db_url = os.environ.get("EVAL_DATABASE_URL")
    if not db_url:
        sys.exit("ERROR: EVAL_DATABASE_URL not set - add it to .env (see .env.example)")

    run_dir = RUNS_DIR / args.run_id
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        sys.exit(f"ERROR: {summary_path} not found")
    conditions = dict(json.loads(summary_path.read_text(encoding="utf-8"))["conditions"])
    if "correction_template" in conditions:
        sys.exit("ERROR: this run records its correction template; eval_run.py wrote generation_prompts/")
    conditions["correction_template"] = {"key": CORRECTION_TEMPLATE_KEY, "version": args.correction_version}

    for path in write_generation_prompts(run_dir, read_template_texts(db_url, templates_used(conditions))):
        print(f"wrote {path.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
