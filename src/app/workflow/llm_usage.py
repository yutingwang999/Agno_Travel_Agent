"""LLM call result with token usage, shared by the generate and validate_output steps.

Token counts come from the ``usage_metadata`` of a Gemini response and are
written to ``trace_events`` (``input_tokens`` / ``output_tokens``), where the
evaluation harness reads them to compute cost.

Public API::

    from app.workflow.llm_usage import LLMResult, result_from_response

    result = result_from_response(client.models.generate_content(...))
    result.text, result.input_tokens, result.output_tokens
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    """Text of one LLM response and its token usage (None when not reported)."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def result_from_response(response: Any) -> LLMResult:
    """Build an :class:`LLMResult` from a Gemini ``GenerateContentResponse``.

    Output tokens include thinking tokens, which Gemini bills as output.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return LLMResult(text=response.text)

    input_tokens = usage.prompt_token_count
    output_tokens = None
    if usage.candidates_token_count is not None or usage.thoughts_token_count is not None:
        output_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return LLMResult(text=response.text, input_tokens=input_tokens, output_tokens=output_tokens)
