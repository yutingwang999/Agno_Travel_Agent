"""Step 5: generate — resolves the prompt template and calls the LLM.

Reads upstream workflow state to build a fully resolved prompt:

- ``destination``, ``trip_length``, ``budget``, ``travel_style``, ``notes`` and
  the optional ``max_daily_budget_aud`` from intake (available in
  ``step_input.additional_data``); budget and amount give ``daily_budget_ceiling``
- ``matched_category``, ``tone``, ``constraints`` from the cag_match SSE event
- ``retrieved_context`` from the rag_retrieve SSE event, each chunk numbered
  with a citation id ``[S1]``, ``[S2]``, ... (empty string when retrieval
  returned nothing); ``context_sources`` in the event maps each id to its chunk

Every request uses the template key ``itinerary_with_context`` (rebuild-rag):
the active version from ``prompt_templates``, or the exact version given by
the ``template_version`` override — never hardcoded.

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

from app.workflow.budget import ceiling_text, daily_budget_ceiling
from app.workflow.llm_usage import LLMResult, result_from_response
from app.workflow.output_validator import STRUCTURED_OUTPUT_CONFIG
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.template_resolver import TemplateNotFoundError, resolve_template
from app.workflow.trace_logger import write_trace

logger = logging.getLogger(__name__)
TEMPLATE_KEY = "itinerary_with_context"
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


def _retrieved_chunks(step_input: StepInput) -> list[dict]:
    """Return the chunk dicts of the rag_retrieve event, or [] when unavailable."""
    content = step_input.get_step_content("rag_retrieve")
    if content is None:
        return []
    try:
        chunks = json.loads(content).get("data", {}).get("retrieved_context") or []
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []
    return [chunk for chunk in chunks if isinstance(chunk, dict)]


def citation_id(position: int) -> str:
    """The citation id of the chunk at 1-based *position*: ``S1``, ``S2``, ..."""
    return f"S{position}"


def _extract_retrieved_context(step_input: StepInput) -> tuple[str, list[dict]]:
    """Number the retrieved chunks as citations and render them for the prompt.

    Each chunk becomes ``"[S{n}] {title}\\n{chunk_text}"`` in retrieval order,
    joined by blank lines, and gets an entry in the returned sources list.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        ``(retrieved_context, context_sources)``: the rendered text, ``""`` when
        no chunks were retrieved, and one ``{"id", "chunk_id", "title",
        "source", "section"}`` dict per chunk placed in the prompt.
    """
    blocks, sources = [], []
    for position, chunk in enumerate(_retrieved_chunks(step_input), start=1):
        cid = citation_id(position)
        title = chunk.get("title") or ""
        blocks.append(f"[{cid}] {title}\n{chunk.get('chunk_text') or ''}")
        sources.append({
            "id": cid,
            "chunk_id": chunk.get("chunk_id"),
            "title": title,
            "source": chunk.get("source"),
            "section": chunk.get("section"),
        })
    return "\n\n".join(blocks), sources


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
        config=STRUCTURED_OUTPUT_CONFIG,
    )
    return result_from_response(response)


def generate_executor(step_input: StepInput) -> StepOutput:
    """Resolve the prompt template and call the LLM.

    Reads normalised input fields from ``step_input.additional_data`` and
    upstream step outputs to build the full set of template variables,
    fetches the ``itinerary_with_context`` template from ``prompt_templates``,
    formats it with the resolved variables, and calls the Gemini LLM.

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
    notes: str = additional_data.get("notes") or ""
    daily_ceiling = daily_budget_ceiling(budget, additional_data.get("max_daily_budget_aud"))

    # Optional template version override forwarded from the API query parameter.
    # None means "use the active version" (default behaviour).
    template_version_override: int | None = additional_data.get("template_version")

    # Read CAG output from the cag_match SSE event
    matched_category: str = _extract_from_step(step_input, "cag_match", "matched_category")
    tone: str = _extract_from_step(step_input, "cag_match", "tone")
    constraints: str = _extract_from_step(step_input, "cag_match", "constraints")

    # Read the knowledge context, numbered for citations — "" when retrieval returned nothing
    retrieved_context, context_sources = _extract_retrieved_context(step_input)

    template_key: str = TEMPLATE_KEY

    # Fetch the prompt template from the database — never hardcode prompt text.
    # None means "use the active version"; an override fetches that exact version.
    try:
        template_text, template_version = resolve_template(
            template_key=template_key,
            db_url=db_url,
            version=template_version_override,
        )
    except TemplateNotFoundError:
        logger.error("generate: no template found for template_key=%r", template_key)
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
        "notes": notes,
        "matched_category": matched_category,
        "tone": tone,
        "constraints": constraints,
        "retrieved_context": retrieved_context,
        "daily_budget_ceiling": ceiling_text(daily_ceiling),
    }
    resolved_prompt: str = _format_template(template_text, variables)

    # Call the LLM with the fully resolved prompt.  Only the exception type goes
    # into the event; the full message stays in the log.
    try:
        llm_result = _call_llm(
            prompt=resolved_prompt,
            api_key=api_key,
            model=llm_model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate: LLM call failed")
        latency_ms = (time.monotonic() - start) * 1000
        write_trace(
            db_url=db_url,
            session_id=session_id,
            step_name="generate",
            status="error",
            latency_ms=latency_ms,
            prompt_template_key=template_key,
            prompt_template_version=template_version,
            error_type="llm_call_failed",
        )
        error_event = build_sse_event(
            session_id=session_id,
            step="generate",
            status="error",
            error=f"LLM call failed: {type(exc).__name__}",
        )
        return StepOutput(content=sse_event_to_json(error_event))
    raw_llm_output: str = llm_result.text

    sse_event = build_sse_event(
        session_id=session_id,
        step="generate",
        status="completed",
        data={
            "raw_llm_output": raw_llm_output,
            "prompt_template_key": template_key,
            "prompt_template_version": template_version,
            "context_sources": context_sources,
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
