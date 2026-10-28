"""build-evaluation-harness: Markdown comparison table across runs."""

import json

import pytest

from evaluation.compare import comparison_table, get, load_summary


def _summary(run_id: str, dirty: bool, recall: float, tags: dict) -> dict:
    return {
        "run_id": run_id, "subset": "smoke", "entries": 10,
        "conditions": {
            "dataset_version": 1, "corpus_version": "v1", "knowledge_table": "travel_docs_v1",
            "generation_model": "gemini-3.1-flash-lite", "judge_model": "gpt-6-luna",
            "judge_prompts": {"faithfulness": 1, "destination": 1}, "price_table_date": "2026-10-25",
            "git_commit": "abcdef1234", "git_dirty": dirty,
            "generation_templates": [{"key": "low_confidence_with_retrieval", "version": 1}],
        },
        "metrics": {
            "slot_extraction": {"value": None, "reason": "no request parser"},
            "retrieval": {"recall_at_k": recall, "mrr_at_k": 1.0},
            "behaviour": {"overall": 0.7, "by_tag": tags},
            "faithfulness": {"overall": {"supported_share": 0.2}, "with_context": {"supported_share": 0.25},
                             "without_context": {"supported_share": 0.0}},
            "constraints": {"trip_length_rate": 1.0, "budget_rate": 0.375, "destination_rate": 1.0},
            "system": {"format_pass_rate": 1.0, "retry_rate": 0.0, "error_rate": 0.0,
                       "latency_p50_ms": 4292.4, "latency_p95_ms": 5087.5,
                       "step_latency_ms": {"generate": {"runs": 10, "mean_ms": 3133.2}}},
            "cost": {"mean_request_usd": 0.0011272, "judge_total_usd": 0.0212},
        },
    }


def test_one_column_per_run_and_one_row_per_metric():
    """Spec scenario: comparing two runs gives one column per run, one row per metric."""
    table = comparison_table([
        _summary("run-a", False, 0.95, {"out_of_scope": 0.0}),
        _summary("run-b", False, 0.80, {"out_of_scope": 1.0, "prompt_injection": 1.0}),
    ])
    lines = table.splitlines()
    assert lines[0] == "| Item | `run-a` | `run-b` |"
    assert all(line.count("|") == 4 for line in lines if line.startswith("|"))
    assert "| Recall@k | 0.950 | 0.800 |" in lines
    assert "| Slot extraction accuracy | N/A (no request parser) | N/A (no request parser) |" in lines
    assert "| Latency p50 | 4.29 s | 4.29 s |" in lines
    assert "| Cost per request | $0.00113 | $0.00113 |" in lines
    assert "| Step latency: `generate` | 3133 ms (n=10) | 3133 ms (n=10) |" in lines
    # tags missing from one run show a dash
    assert "| Behaviour correctness: `prompt_injection` | — | 100.0% |" in lines
    assert "⚠️" not in table


def test_dirty_run_is_marked():
    """Spec scenario: a run with uncommitted changes is marked with a warning."""
    table = comparison_table([_summary("clean", False, 0.9, {}), _summary("dirty", True, 0.9, {})])
    header = table.splitlines()[0]
    assert header == "| Item | `clean` | ⚠️ dirty |"
    assert "`abcdef1` ⚠️ uncommitted" in table
    assert table.splitlines()[-1].startswith("⚠️ Run made with uncommitted changes")


def test_get_reads_dotted_paths():
    summary = {"metrics": {"retrieval": {"recall_at_k": 0.5}}}
    assert get(summary, "metrics.retrieval.recall_at_k") == 0.5
    assert get(summary, "metrics.retrieval.missing") is None
    assert get(summary, "metrics.retrieval.recall_at_k.deeper") is None


def test_needs_a_run():
    with pytest.raises(ValueError):
        comparison_table([])


def test_load_summary(tmp_path):
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / "summary.json").write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    assert load_summary("r1", tmp_path)["run_id"] == "r1"
    with pytest.raises(FileNotFoundError, match="no summary"):
        load_summary("nope", tmp_path)


def test_correction_template_row():
    """Runs that record their correction template show it; older runs show a dash."""
    recorded = _summary("run-new", False, 0.9, {})
    recorded["conditions"]["correction_template"] = {"key": "validate_output_correction", "version": 2}
    table = comparison_table([_summary("run-old", False, 0.9, {}), recorded])
    assert "| Correction template | — | validate_output_correction v2 |" in table.splitlines()
