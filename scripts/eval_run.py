"""
Run one evaluation configuration over the dataset and write eval/runs/<run id>/.

Usage:
    python scripts/eval_run.py --config v010-baseline
    python scripts/eval_run.py --config v010-baseline --subset smoke
    python scripts/eval_run.py --config v010-baseline --entries e001,e026

Needs EVAL_DATABASE_URL (prepared with `python scripts/dev.py eval-db-setup`),
GEMINI_API_KEY and OPENAI_API_KEY. The app runs in-process against the evaluation
database; the development and test databases are never touched.
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
from sqlalchemy import make_url  # noqa: E402

from evaluation.runner import (  # noqa: E402
    RUNS_DIR,
    git_state,
    load_config,
    load_subset,
    make_run_id,
    select_entries,
    utc_now,
)

EVAL_DB_SUFFIX = "_eval_db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="configuration name in eval/configs/")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--subset", help="subset name in eval/subsets/ (e.g. smoke)")
    group.add_argument("--entries", help="comma-separated entry ids, for debugging")
    return parser.parse_args()


def configure_environment(config) -> str:
    """Point the app at the evaluation database and the run's models. Must run before importing the app."""
    load_dotenv(os.path.join(ROOT_DIR, ".env"), override=False)
    url = os.environ.get("EVAL_DATABASE_URL")
    if not url:
        sys.exit("ERROR: EVAL_DATABASE_URL not set - add it to .env (see .env.example)")
    if not (make_url(url).database or "").endswith(EVAL_DB_SUFFIX):
        sys.exit(f"ERROR: EVAL_DATABASE_URL must name a database ending with {EVAL_DB_SUFFIX!r}")
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        if not os.environ.get(key):
            sys.exit(f"ERROR: {key} not set")
    os.environ.update(
        DATABASE_URL=url,
        KNOWLEDGE_TABLE_NAME=config.knowledge_table,
        LLM_MODEL=config.generation_model,
        EMBEDDING_MODEL=config.embedding_model,
        JUDGE_MODEL=config.judge_model,
        AGNO_TELEMETRY="false",
    )
    return url


def check_database(db_url: str, knowledge_table: str) -> None:
    """Fail before creating the run directory if the evaluation database is not ready."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        knowledge = set(inspector.get_table_names(schema="ai"))
    except OperationalError as exc:
        sys.exit(f"ERROR: cannot connect to the evaluation database ({exc.orig}). "
                 "Is Postgres running? (python scripts/dev.py up)")
    finally:
        engine.dispose()
    if "trace_events" not in tables or knowledge_table not in knowledge:
        sys.exit(f"ERROR: evaluation database is not prepared (missing trace_events or ai.{knowledge_table}); "
                 "run: python scripts/dev.py eval-db-setup")


def make_services(client, config, db_url: str):
    from pydantic import ValidationError
    from sqlalchemy import create_engine, text

    from app.main import build_additional_data
    from app.workflow.intake_model import TravelRequest
    from app.workflow.knowledge_base import build_knowledge
    from app.workflow.retrieval_service import _search_knowledge
    from app.workflow.steps.cag_match import _build_intent_text
    from evaluation.judge import Judge
    from evaluation.retrieval import workflow_query_text
    from evaluation.runner import Services

    engine = create_engine(db_url)
    api_key = os.environ["GEMINI_API_KEY"]

    def send(form: dict) -> tuple[int, str]:
        response = client.post("/generate", json=form)
        return response.status_code, response.text

    def retrieve(query: str) -> list:
        # Not retrieve_documents(): it turns failures into an empty result,
        # which would read as Recall = 0 instead of an error.
        knowledge = build_knowledge(db_url=db_url, api_key=api_key, embedding_model=config.embedding_model)
        return _search_knowledge(knowledge, query, config.retrieval_k)

    def trace_rows(session_id: str) -> list[dict]:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT step_name, status, latency_ms, prompt_template_key, prompt_template_version, "
                     "degraded_mode, error_type, input_tokens, output_tokens "
                     "FROM trace_events WHERE session_id = :sid ORDER BY id"),
                {"sid": session_id},
            )
            return [dict(row._mapping) for row in rows]

    def intent_text(form: dict) -> str | None:
        try:
            request = TravelRequest.model_validate(form)
        except ValidationError:
            return None
        return _build_intent_text(build_additional_data("eval", request))

    return Services(send=send, query_text=workflow_query_text, retrieve=retrieve,
                    trace_rows=trace_rows, intent_text=intent_text, judge=Judge.from_env())


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    db_url = configure_environment(config)

    from fastapi.testclient import TestClient

    from app.main import app
    from evaluation.cost import load_pricing
    from evaluation.dataset import load_dataset, load_meta
    from evaluation.runner import append_jsonl, result_record, run, summarise, write_prompt_copies

    check_database(db_url, config.knowledge_table)
    meta = load_meta()
    if meta.corpus_version != config.corpus_version:
        sys.exit(f"ERROR: dataset is labelled for corpus {meta.corpus_version!r}, "
                 f"config {config.name!r} uses {config.corpus_version!r}")
    ids = load_subset(args.subset) if args.subset else (args.entries.split(",") if args.entries else None)
    entries = select_entries(load_dataset(), ids)
    pricing = load_pricing()
    commit, dirty = git_state()
    started = utc_now()
    run_id = make_run_id(config.name, args.subset or ("entries" if args.entries else None), started)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    print(f"run {run_id}: {len(entries)} entries, git {commit[:7]}{' (dirty)' if dirty else ''}")

    # One TestClient context for the whole run: a new event loop per request breaks
    # sse-starlette's shared asyncio.Event and fails every request after the first.
    phase_seconds: dict = {}
    with TestClient(app) as client:
        services = make_services(client, config, db_url)
        results = run(entries, config, services, pricing,
                      on_result=lambda r: append_jsonl(run_dir / "results.jsonl", result_record(r)),
                      phase_seconds=phase_seconds)

    write_prompt_copies(run_dir, services.judge)
    finished = utc_now()
    summary = {
        "run_id": run_id,
        "subset": args.subset or ("entries" if args.entries else "all"),
        "entries": len(entries),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "phase_seconds": {"total": round((finished - started).total_seconds(), 2), **phase_seconds},
        "conditions": {
            "dataset_version": meta.dataset_version,
            "corpus_version": meta.corpus_version,
            "knowledge_table": config.knowledge_table,
            "config": config.model_dump(),
            "generation_model": config.generation_model,
            "embedding_model": config.embedding_model,
            "judge_model": config.judge_model,
            "judge_prompts": services.judge.prompt_versions,
            "price_table_date": pricing.date.isoformat(),
            "git_commit": commit,
            "git_dirty": dirty,
        },
        **summarise(results, config, pricing),
    }
    summary["conditions"]["generation_templates"] = summary.pop("generation_templates")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")

    metrics = summary["metrics"]
    print(f"behaviour correct: {metrics['behaviour']['overall']}  |  error rate: {metrics['system']['error_rate']}")
    print(f"recall@{config.retrieval_k}: {metrics['retrieval']['recall_at_k']}  |  "
          f"faithfulness: {metrics['faithfulness']['overall']['supported_share']}")
    print(f"wrote {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
