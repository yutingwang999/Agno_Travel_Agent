"""Generation prompt copies in a run directory (harden-workflow-guardrails task 6.6)."""

import pytest

from evaluation.templates import templates_used, write_generation_prompts


def test_templates_used_includes_correction_template():
    conditions = {
        "generation_templates": [
            {"key": "low_confidence_with_retrieval", "version": 2},
            {"key": "high_confidence_minimal_context", "version": 2},
        ],
        "correction_template": {"key": "validate_output_correction", "version": 2},
    }
    assert templates_used(conditions) == [
        ("high_confidence_minimal_context", 2),
        ("low_confidence_with_retrieval", 2),
        ("validate_output_correction", 2),
    ]


def test_templates_used_without_correction_template():
    """Runs made before the correction template was recorded list generation templates only."""
    conditions = {"generation_templates": [{"key": "low_confidence_with_retrieval", "version": 1}]}
    assert templates_used(conditions) == [("low_confidence_with_retrieval", 1)]


def test_write_generation_prompts(tmp_path):
    texts = {("low_confidence_with_retrieval", 2): "Plan {destination}.\n{{ literal }}\n"}
    paths = write_generation_prompts(tmp_path, texts)

    assert [p.name for p in paths] == ["low_confidence_with_retrieval_v2.txt"]
    assert paths[0].parent.name == "generation_prompts"
    assert paths[0].read_bytes() == b"Plan {destination}.\n{{ literal }}\n"


def test_write_generation_prompts_never_overwrites(tmp_path):
    texts = {("low_confidence_with_retrieval", 2): "first"}
    write_generation_prompts(tmp_path, texts)
    with pytest.raises(FileExistsError):
        write_generation_prompts(tmp_path, {("low_confidence_with_retrieval", 2): "second"})
    assert (tmp_path / "generation_prompts" / "low_confidence_with_retrieval_v2.txt").read_text() == "first"
