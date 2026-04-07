"""Step 1: intake — validates and normalises user input.

Reads the four required travel planning fields from ``step_input.additional_data``,
validates them with the ``TravelRequest`` Pydantic model, and writes the
normalised values into the SSE event ``data`` field so downstream steps can
read them via ``step_input.get_step_content("intake")``.

Raises:
    pydantic.ValidationError: when a required field is missing or fails
        validation.  FastAPI maps this to a 422 Unprocessable Entity response.
        The executor does NOT catch this exception.
"""

import os
import time

from agno.workflow.types import StepInput, StepOutput

from app.workflow.intake_model import TravelRequest
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.trace_logger import write_trace


def intake_executor(step_input: StepInput) -> StepOutput:
    """Validate and normalise the travel planning request.

    Extracts ``destination``, ``trip_length``, ``budget``, and
    ``travel_style`` from ``step_input.additional_data`` and validates them
    using :class:`TravelRequest`.  Raises ``pydantic.ValidationError`` — which
    FastAPI converts to a 422 response — if any required field is missing or
    invalid.

    Returns a :class:`StepOutput` whose ``content`` is a JSON-serialised SSE
    event.  The event's ``data`` field contains the four normalised fields so
    downstream steps can access them.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")
    db_url: str = os.environ.get("DATABASE_URL", "")

    start = time.monotonic()

    # Validate and normalise — raises ValidationError (→ 422) on bad input.
    travel_request = TravelRequest.model_validate(additional_data)

    normalised_fields = {
        "destination": travel_request.destination,
        "trip_length": travel_request.trip_length,
        "budget": travel_request.budget,
        "travel_style": travel_request.travel_style,
    }

    sse_event = build_sse_event(
        session_id=session_id,
        step="intake",
        status="completed",
        data=normalised_fields,
    )

    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="intake",
        status="completed",
        latency_ms=latency_ms,
    )

    return StepOutput(content=sse_event_to_json(sse_event))
