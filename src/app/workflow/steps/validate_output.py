"""Step 6: validate_output — validates LLM output against a Pydantic schema.

Reads ``raw_llm_output`` from the generate step's SSE event and validates it
against the :class:`~app.workflow.output_validator.ItineraryOutput` schema.

On first validation failure:
    - Fetches the ``validate_output_correction`` prompt template from the DB.
    - Calls the LLM with a corrective prompt (invalid output + error details).
    - Sets ``degraded_mode=True`` in the SSE event data field.

On second failure (retry also fails):
    - Returns a structured error response (``status="error"``).
    - Sets ``degraded_mode=True``.
    - Does NOT raise an unhandled exception.

Valid output is passed through unchanged with ``degraded_mode=False``.
"""

import json
import logging
import os
import re
import time

from agno.workflow.types import StepInput, StepOutput
from google import genai

from app.workflow.llm_usage import LLMResult, result_from_response
from app.workflow.output_validator import parse_llm_output
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.template_resolver import TemplateNotFoundError, resolve_template
from app.workflow.trace_logger import write_trace

logger = logging.getLogger(__name__)

CORRECTION_TEMPLATE_KEY = "validate_output_correction"
DEFAULT_LLM_MODEL = "gemini-3.1-flash-lite"


def _extract_raw_llm_output(step_input: StepInput) -> str:
    """Extract ``raw_llm_output`` from the generate step's SSE event.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        The raw LLM output string, or an empty string if unavailable.
    """
    content = step_input.get_step_content("generate")
    if content is None:
        return ""
    try:
        event = json.loads(content)
        return str(event.get("data", {}).get("raw_llm_output", ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def _build_correction_prompt(
    template_text: str,
    raw_llm_output: str,
    validation_errors: str,
) -> str:
    """Substitute ``{validation_errors}`` and ``{raw_llm_output}`` placeholders.

    Uses a regex replacer (same approach as the generate step) so that any
    literal ``{`` / ``}`` in the schema example within the template are left
    untouched.

    Args:
        template_text:     Raw correction template string from the database.
        raw_llm_output:    The invalid LLM output to be corrected.
        validation_errors: Human-readable Pydantic/JSON error details.

    Returns:
        The fully resolved correction prompt string.
    """
    variables = {
        "validation_errors": validation_errors,
        "raw_llm_output": raw_llm_output,
    }

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


def validate_output_executor(step_input: StepInput) -> StepOutput:
    """Validate raw LLM output against the ItineraryOutput Pydantic schema.

    Reads ``raw_llm_output`` from the generate step's SSE event and attempts
    Pydantic validation.  Retries exactly once using a corrective prompt on
    failure.  Never raises an unhandled exception — all failures produce a
    structured SSE error event.

    Args:
        step_input: Agno step input carrying previous step outputs and
                    session metadata in ``additional_data``.

    Returns:
        A :class:`StepOutput` whose ``content`` is a JSON-serialised SSE event.
        On success the ``data`` field contains ``itinerary`` and
        ``degraded_mode``.  On unrecoverable failure the event has
        ``status="error"`` and ``degraded_mode=True``.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")

    raw_llm_output: str = _extract_raw_llm_output(step_input)

    start = time.monotonic()

    # ------------------------------------------------------------------ #
    # First validation attempt                                             #
    # ------------------------------------------------------------------ #
    validated_output, first_errors = parse_llm_output(raw_llm_output)

    if validated_output is not None:
        sse_event = build_sse_event(
            session_id=session_id,
            step="validate_output",
            status="completed",
            data={
                "itinerary": validated_output.model_dump(),
                "degraded_mode": False,
            },
        )
        latency_ms = (time.monotonic() - start) * 1000
        write_trace(
            db_url=os.environ.get("DATABASE_URL", ""),
            session_id=session_id,
            step_name="validate_output",
            status="completed",
            latency_ms=latency_ms,
            degraded_mode=False,
        )
        return StepOutput(content=sse_event_to_json(sse_event))

    # ------------------------------------------------------------------ #
    # First attempt failed — retry once with a corrective prompt           #
    # ------------------------------------------------------------------ #
    logger.warning(
        "validate_output: first validation failed (session_id=%r): %s",
        session_id,
        first_errors,
    )

    db_url: str = os.environ["DATABASE_URL"]
    api_key: str = os.environ["GEMINI_API_KEY"]
    llm_model: str = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)

    try:
        correction_template_text, _ = resolve_template(
            template_key=CORRECTION_TEMPLATE_KEY,
            db_url=db_url,
        )
    except TemplateNotFoundError:
        logger.error(
            "validate_output: correction template %r not found in prompt_templates — "
            "cannot retry; returning structured error",
            CORRECTION_TEMPLATE_KEY,
        )
        sse_event = build_sse_event(
            session_id=session_id,
            step="validate_output",
            status="error",
            data={"degraded_mode": True},
            error=f"Validation failed and correction template unavailable: {first_errors}",
        )
        latency_ms = (time.monotonic() - start) * 1000
        write_trace(
            db_url=db_url,
            session_id=session_id,
            step_name="validate_output",
            status="error",
            latency_ms=latency_ms,
            degraded_mode=True,
            error_type="correction_template_unavailable",
        )
        return StepOutput(content=sse_event_to_json(sse_event))

    correction_prompt = _build_correction_prompt(
        template_text=correction_template_text,
        raw_llm_output=raw_llm_output,
        validation_errors=first_errors,
    )

    retry_result = _call_llm(
        prompt=correction_prompt,
        api_key=api_key,
        model=llm_model,
    )
    retry_raw_output: str = retry_result.text

    retry_output, retry_errors = parse_llm_output(retry_raw_output)

    if retry_output is not None:
        # Retry succeeded — mark degraded because a retry was needed
        sse_event = build_sse_event(
            session_id=session_id,
            step="validate_output",
            status="completed",
            data={
                "itinerary": retry_output.model_dump(),
                "degraded_mode": True,
            },
        )
        latency_ms = (time.monotonic() - start) * 1000
        write_trace(
            db_url=db_url,
            session_id=session_id,
            step_name="validate_output",
            status="completed",
            latency_ms=latency_ms,
            degraded_mode=True,
            error_type="validation_retry_succeeded",
            input_tokens=retry_result.input_tokens,
            output_tokens=retry_result.output_tokens,
        )
        return StepOutput(content=sse_event_to_json(sse_event))

    # ------------------------------------------------------------------ #
    # Retry also failed — structured error, no unhandled exception         #
    # ------------------------------------------------------------------ #
    logger.error(
        "validate_output: retry validation also failed (session_id=%r): %s",
        session_id,
        retry_errors,
    )

    sse_event = build_sse_event(
        session_id=session_id,
        step="validate_output",
        status="error",
        data={"degraded_mode": True},
        error=f"Validation failed after retry: {retry_errors}",
    )
    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="validate_output",
        status="error",
        latency_ms=latency_ms,
        degraded_mode=True,
        error_type="validation_failed_after_retry",
        input_tokens=retry_result.input_tokens,
        output_tokens=retry_result.output_tokens,
    )
    return StepOutput(content=sse_event_to_json(sse_event))
