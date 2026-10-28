"""Cost per request and judge cost, computed from token counts and a dated price table.

Three parts:

- generation — tokens recorded on the trace rows of the steps that call the LLM
               (generate, and validate_output's corrective call)
- embedding  — the embedding API reports no token counts, so tokens are estimated
               from the embedded text's length (``embedding_chars_per_token``)
- judge      — tokens reported by the judge model; the cost of evaluation, not of
               the product, so it is reported separately and not added per request

Prices live in ``eval/pricing.yaml`` (USD per 1M tokens) and are never hardcoded::

    date: 2026-10-25
    currency: USD
    embedding_chars_per_token: 4
    models:
      gemini-3.1-flash-lite: {input: 0.25, output: 1.50}
      gpt-6-luna:            {input: 0.10, output: 0.50}

Public API::

    from evaluation.cost import load_pricing, request_cost, summarize_costs
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from evaluation.dataset import ROOT_DIR

PRICING_PATH = ROOT_DIR / "eval" / "pricing.yaml"
LLM_STEPS = ("generate", "validate_output")
_PER_TOKEN = 1 / 1_000_000


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="allow")  # free-form notes such as source / verified

    input: float = Field(ge=0)
    output: float = Field(default=0.0, ge=0)


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    currency: str
    embedding_chars_per_token: float = Field(gt=0)
    models: dict[str, ModelPrice]

    def price(self, model: str) -> ModelPrice:
        try:
            return self.models[model]
        except KeyError:
            raise KeyError(f"model {model!r} is not in the price table ({PRICING_PATH.name})") from None


def load_pricing(path: Path = PRICING_PATH) -> Pricing:
    return Pricing.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def token_cost(model: str, input_tokens: int, output_tokens: int, pricing: Pricing) -> float:
    price = pricing.price(model)
    return (input_tokens * price.input + output_tokens * price.output) * _PER_TOKEN


def embedding_cost(texts: list[str], model: str, pricing: Pricing) -> float:
    """Estimated cost of embedding *texts*: characters / chars-per-token, input price."""
    tokens = sum(len(text) for text in texts) / pricing.embedding_chars_per_token
    return tokens * pricing.price(model).input * _PER_TOKEN


@dataclass(frozen=True)
class RequestCost:
    generation_usd: float
    embedding_usd: float
    # True when an LLM step's trace row has no token counts, so generation is understated.
    missing_usage: bool

    @property
    def total_usd(self) -> float:
        return self.generation_usd + self.embedding_usd


def request_cost(
    trace_rows: list[dict],
    embedding_texts: list[str],
    generation_model: str,
    embedding_model: str,
    pricing: Pricing,
) -> RequestCost:
    """Cost of one request from its trace rows and the texts it embedded.

    Only the LLM steps' rows are read; validate_output's row has tokens only when
    the corrective call ran, so a missing count there is not "missing usage".
    """
    generation = 0.0
    missing = False
    for row in trace_rows:
        if row.get("step_name") not in LLM_STEPS:
            continue
        input_tokens, output_tokens = row.get("input_tokens"), row.get("output_tokens")
        if input_tokens is None and output_tokens is None:
            if row["step_name"] == "generate" and row.get("status") == "completed":
                missing = True
            continue
        generation += token_cost(generation_model, input_tokens or 0, output_tokens or 0, pricing)
    return RequestCost(
        generation_usd=generation,
        embedding_usd=embedding_cost(embedding_texts, embedding_model, pricing),
        missing_usage=missing,
    )


def summarize_costs(
    request_costs: list[RequestCost],
    judge_usage: list[tuple[int, int]],
    judge_model: str,
    pricing: Pricing,
) -> dict:
    """Mean cost per request (generation + embedding) and the total judge cost."""
    n = len(request_costs)
    judge_total = sum(token_cost(judge_model, i, o, pricing) for i, o in judge_usage)
    return {
        "currency": pricing.currency,
        "price_table_date": pricing.date.isoformat(),
        "requests": n,
        "mean_generation_usd": sum(c.generation_usd for c in request_costs) / n if n else None,
        "mean_embedding_usd": sum(c.embedding_usd for c in request_costs) / n if n else None,
        "mean_request_usd": sum(c.total_usd for c in request_costs) / n if n else None,
        "requests_missing_usage": sum(c.missing_usage for c in request_costs),
        "judge_calls": len(judge_usage),
        "judge_total_usd": judge_total,
    }
