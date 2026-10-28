"""build-evaluation-harness: cost computation with a fixed price table."""

import pytest

from evaluation.cost import (
    Pricing,
    embedding_cost,
    load_pricing,
    request_cost,
    summarize_costs,
    token_cost,
)

PRICING = Pricing.model_validate({
    "date": "2026-10-25",
    "currency": "USD",
    "embedding_chars_per_token": 4,
    "models": {
        "gen": {"input": 0.25, "output": 1.50},
        "emb": {"input": 0.20},
        "judge": {"input": 0.10, "output": 0.50},
    },
})


def test_token_cost_per_million():
    assert token_cost("gen", 1_000_000, 0, PRICING) == pytest.approx(0.25)
    assert token_cost("gen", 1200, 800, PRICING) == pytest.approx((1200 * 0.25 + 800 * 1.50) / 1e6)


def test_unknown_model_names_the_price_table():
    with pytest.raises(KeyError, match="not in the price table"):
        token_cost("nope", 1, 1, PRICING)


def test_embedding_cost_estimated_from_characters():
    # 4,000,000 characters / 4 chars per token = 1M tokens at $0.20
    assert embedding_cost(["x" * 4_000_000], "emb", PRICING) == pytest.approx(0.20)
    assert embedding_cost([], "emb", PRICING) == 0


def test_request_cost_sums_generate_and_correction_tokens():
    rows = [
        {"step_name": "intake", "status": "completed"},
        {"step_name": "generate", "status": "completed", "input_tokens": 1200, "output_tokens": 800},
        {"step_name": "validate_output", "status": "completed", "input_tokens": 300, "output_tokens": 450},
    ]
    cost = request_cost(rows, ["a" * 400], "gen", "emb", PRICING)
    expected_generation = ((1200 + 300) * 0.25 + (800 + 450) * 1.50) / 1e6
    assert cost.generation_usd == pytest.approx(expected_generation)
    assert cost.embedding_usd == pytest.approx(100 * 0.20 / 1e6)
    assert cost.total_usd == pytest.approx(expected_generation + 100 * 0.20 / 1e6)
    assert cost.missing_usage is False


def test_validate_output_without_correction_is_not_missing_usage():
    rows = [
        {"step_name": "generate", "status": "completed", "input_tokens": 10, "output_tokens": 10},
        {"step_name": "validate_output", "status": "completed"},
    ]
    assert request_cost(rows, [], "gen", "emb", PRICING).missing_usage is False


def test_generate_row_without_tokens_is_flagged():
    rows = [{"step_name": "generate", "status": "completed"}]
    assert request_cost(rows, [], "gen", "emb", PRICING).missing_usage is True


def test_summary_reports_judge_separately_with_price_date():
    """Spec scenario: per-request cost split into generation and embedding, total judge cost, price date."""
    costs = [
        request_cost([{"step_name": "generate", "status": "completed", "input_tokens": 1_000_000,
                       "output_tokens": 0}], [], "gen", "emb", PRICING),
        request_cost([{"step_name": "generate", "status": "completed", "input_tokens": 0,
                       "output_tokens": 0}], ["x" * 4_000_000], "gen", "emb", PRICING),
    ]
    summary = summarize_costs(costs, judge_usage=[(1_000_000, 1_000_000)], judge_model="judge", pricing=PRICING)

    assert summary["price_table_date"] == "2026-10-25"
    assert summary["mean_generation_usd"] == pytest.approx(0.125)
    assert summary["mean_embedding_usd"] == pytest.approx(0.10)
    assert summary["mean_request_usd"] == pytest.approx(0.225)
    assert summary["judge_total_usd"] == pytest.approx(0.60)
    assert summary["judge_calls"] == 1


def test_repository_price_table_covers_the_configured_models():
    pricing = load_pricing()
    for model in ("gemini-3.1-flash-lite", "gemini-embedding-001", "gpt-6-luna"):
        assert pricing.price(model).input > 0
    assert pricing.currency == "USD"


def test_load_pricing_from_yaml(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text(
        "date: 2026-10-25\ncurrency: USD\nembedding_chars_per_token: 4\n"
        "models:\n  gen: {input: 0.25, output: 1.50, source: 'https://example'}\n",
        encoding="utf-8",
    )
    pricing = load_pricing(path)
    assert pricing.price("gen").output == 1.50
