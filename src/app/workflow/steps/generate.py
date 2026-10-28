"""Step 5: generate — resolves the active prompt template and calls the LLM.

Reads upstream workflow state to build a fully resolved prompt:

- ``destination``, ``trip_length``, ``budget``, ``travel_style`` from intake
  (available in ``step_input.additional_data``)
- ``matched_category``, ``confidence_score``, ``tone``, ``constraints`` from
  the cag_match SSE event
- ``retrieved_context`` from the rag_retrieve SSE event (empty string when
  rag_retrieve was skipped due to high confidence)

Template key selection:
    confidence_score >= 0.85  →  ``high_confidence_minimal_context``
    confidence_score <  0.85  →  ``low_confidence_with_retrieval``

The active versioned template is fetched from ``prompt_templates`` by
``template_key`` and ``is_active=True`` — never hardcoded.

Writes ``raw_llm_output`` and ``prompt_template_version`` to the SSE event
``data`` field for downstream steps.
"""

import json
import logging
import os
import re
import time

from agno.workflow.types import StepInput, StepOutput
from google import genai

from app.workflow.config import RETRIEVAL_CONFIDENCE_THRESHOLD
from app.workflow.llm_usage import LLMResult, result_from_response
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.template_resolver import TemplateNotFoundError, resolve_template
from app.workflow.trace_logger import write_trace

logger = logging.getLogger(__name__)
HIGH_CONFIDENCE_TEMPLATE_KEY = "high_confidence_minimal_context"
LOW_CONFIDENCE_TEMPLATE_KEY = "low_confidence_with_retrieval"
DEFAULT_LLM_MODEL = "gemini-3.1-flash-lite"


def _extract_from_step(step_input: StepInput, step_name: str, field: str) -> str:
    """Extract a single field value from a previous step's SSE event data.

    Args:
        step_input: Agno step input carrying previous step outputs.
        step_name:  Name of the step whose output to read (e.g. ``"cag_match"``).
        field:      Key to extract from the SSE event ``data`` dict.

    Returns:
        The string value of the field, or an empty string if unavailable.
    """
    content = step_input.get_step_content(step_name)
    if content is None:
        return ""
    try:
        event = json.loads(content)
        return str(event.get("data", {}).get(field, ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def _extract_confidence_score(step_input: StepInput) -> float:
    """Extract the numeric confidence_score from the cag_match SSE event.

    Falls back to 0.0 (retrieval path) if the value is unavailable.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        The confidence_score float, or 0.0 on failure.
    """
    raw = _extract_from_step(step_input, "cag_match", "confidence_score")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def _extract_retrieved_context(step_input: StepInput) -> str:
    """Build a plain-text block from the rag_retrieve chunk list.

    Joins each retrieved chunk's title and text into a single string for
    injection into the low-confidence prompt template.  Returns an empty
    string if rag_retrieve did not run or returned no chunks.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        A newline-separated string of document chunks, or ``""`` if none.
    """
    content = step_input.get_step_content("rag_retrieve")
    if content is None:
        return ""
    try:
        event = json.loads(content)
        chunks = event.get("data", {}).get("retrieved_context", [])
    except (json.JSONDecodeError, TypeError):
        return ""

    if not chunks:
        return ""

    parts = []
    for chunk in chunks:
        title = chunk.get("title", "")
        chunk_text = chunk.get("chunk_text", "")
        if title:
            parts.append(f"[{title}]\n{chunk_text}")
        else:
            parts.append(chunk_text)

    return "\n\n".join(parts)


def _select_template_key(confidence_score: float) -> str:
    """Choose the prompt template key based on the CAG confidence score.

    Args:
        confidence_score: The cosine similarity score from the cag_match step.

    Returns:
        ``"high_confidence_minimal_context"`` when confidence is at or above
        the 0.85 threshold; ``"low_confidence_with_retrieval"`` otherwise.
    """
    if confidence_score >= RETRIEVAL_CONFIDENCE_THRESHOLD:
        return HIGH_CONFIDENCE_TEMPLATE_KEY
    return LOW_CONFIDENCE_TEMPLATE_KEY


def _format_template(template_text: str, variables: dict) -> str:
    """Substitute known ``{variable}`` placeholders in *template_text*.

    Uses regex to replace only valid Python-identifier placeholders
    (``{destination}``, ``{trip_length}``, etc.), leaving the literal
    ``{`` and ``}`` characters in the JSON schema example untouched.

    Args:
        template_text: Raw template string retrieved from the database.
        variables:     Mapping of variable name to value.

    Returns:
        The template text with all known placeholders replaced.
    """
    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        return str(variables.get(key, match.group(0)))

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _replacer, template_text)


def _call_llm(prompt: str, api_key: str, model: str) -> LLMResult:
    """Send *prompt* to the Gemini LLM and return the generated text and token usage.

    Args:
        prompt:  The fully resolved prompt string.
        api_key: Gemini API key.
        model:   Gemini model name (e.g. ``"gemini-3.1-flash-lite"``).

    Returns:
        The raw text response from the LLM with its token counts.
    """
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    return result_from_response(response)


def generate_executor(step_input: StepInput) -> StepOutput:
    """Resolve the active prompt template and call the LLM.

    Reads normalised input fields from ``step_input.additional_data`` and
    upstream step outputs to build the full set of template variables.
    Selects the appropriate template key based on the CAG confidence score,
    fetches the active template from ``prompt_templates``, formats it with
    the resolved variables, and calls the Gemini LLM.

    Writes ``raw_llm_output`` and ``prompt_template_version`` to the SSE
    event ``data`` field.

    Args:
        step_input: Agno step input carrying previous step outputs and
                    session metadata in ``additional_data``.

    Returns:
        A :class:`StepOutput` whose ``content`` is a JSON-serialised SSE event
        with ``raw_llm_output`` and ``prompt_template_version`` in ``data``.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")

    db_url: str = os.environ["DATABASE_URL"]
    api_key: str = os.environ["GEMINI_API_KEY"]
    llm_model: str = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)

    start = time.monotonic()

    # Read intake fields — available in additional_data (set by the API layer)
    destination: str = additional_data.get("destination", "")
    trip_length: str = str(additional_data.get("trip_length", ""))
    budget: str = additional_data.get("budget", "")
    travel_style: str = additional_data.get("travel_style", "")

    # Optional template version override forwarded from the API query parameter.
    # None means "use the active version" (default behaviour).
    template_version_override: int | None = additional_data.get("template_version")

    # Read CAG output from the cag_match SSE event
    confidence_score: float = _extract_confidence_score(step_input)
    matched_category: str = _extract_from_step(step_input, "cag_match", "matched_category")
    tone: str = _extract_from_step(step_input, "cag_match", "tone")
    constraints: str = _extract_from_step(step_input, "cag_match", "constraints")

    # Read optional RAG context — empty string when rag_retrieve was skipped
    retrieved_context: str = _extract_retrieved_context(step_input)

    # Choose template based on confidence threshold
    template_key: str = _select_template_key(confidence_score)

    # Fetch the prompt template from the database — never hardcode prompt text.
    # When a version override is present, fetch that specific version.
    # Otherwise, fetch the active version and fall back to low_confidence on failure.
    try:
        template_text, template_version = resolve_template(
            template_key=template_key,
            db_url=db_url,
            version=template_version_override,
        )
    except TemplateNotFoundError:
        logger.error(
            "generate: active template not found for template_key=%r — "
            "falling back to low_confidence_with_retrieval",
            template_key,
        )
        fallback_key = LOW_CONFIDENCE_TEMPLATE_KEY
        try:
            if template_key != fallback_key:
                template_text, template_version = resolve_template(
                    template_key=fallback_key,
                    db_url=db_url,
                    version=template_version_override,
                )
            else:
                raise TemplateNotFoundError(
                    f"No active template found for template_key={template_key!r}"
                )
        except TemplateNotFoundError:
            latency_ms = (time.monotonic() - start) * 1000
            write_trace(
                db_url=db_url,
                session_id=session_id,
                step_name="generate",
                status="error",
                latency_ms=latency_ms,
            )
            error_event = build_sse_event(
                session_id=session_id,
                step="generate",
                status="error",
                error=f"No active template found for key {template_key!r}",
            )
            return StepOutput(content=sse_event_to_json(error_event))

    # Format the template by substituting all known variables
    variables = {
        "destination": destination,
        "trip_length": trip_length,
        "budget": budget,
        "travel_style": travel_style,
        "matched_category": matched_category,
        "tone": tone,
        "constraints": constraints,
        "retrieved_context": retrieved_context,
    }
    resolved_prompt: str = _format_template(template_text, variables)

    # Call the LLM with the fully resolved prompt
    llm_result = _call_llm(
        prompt=resolved_prompt,
        api_key=api_key,
        model=llm_model,
    )
    raw_llm_output: str = llm_result.text

    sse_event = build_sse_event(
        session_id=session_id,
        step="generate",
        status="completed",
        data={
            "raw_llm_output": raw_llm_output,
            "prompt_template_key": template_key,
            "prompt_template_version": template_version,
        },
    )

    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="generate",
        status="completed",
        latency_ms=latency_ms,
        prompt_template_key=template_key,
        prompt_template_version=template_version,
        input_tokens=llm_result.input_tokens,
        output_tokens=llm_result.output_tokens,
    )

    return StepOutput(content=sse_event_to_json(sse_event))
