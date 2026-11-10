"""Step 3: retrieval_decision — the routing step before rag_retrieve.

Under the interim routing rule of ``rebuild-rag`` every request goes to
``rag_retrieve``: the CAG confidence measures similarity to an itinerary
category, not whether destination knowledge is needed.  The step is kept so a
redesigned routing rule (roadmap item 3) has a place to plug in, and so the
event structure does not change twice.

The event reports ``routing_decision`` (always ``"rag_retrieve"``) and the
``confidence_score`` from cag_match, for information only.
"""

import json
import os
import time

from agno.workflow.types import StepInput, StepOutput

from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.trace_logger import write_trace

ROUTING_DECISION = "rag_retrieve"


def retrieval_decision_executor(step_input: StepInput) -> StepOutput:
    """Emit the routing decision: every request goes to rag_retrieve.

    Writes ``routing_decision`` and the cag_match ``confidence_score`` to the
    SSE event ``data`` field.

    Args:
        step_input: Agno step input carrying previous step outputs and
                    session metadata in ``additional_data``.

    Returns:
        A StepOutput whose content is the JSON-serialised SSE event.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")
    db_url: str = os.environ.get("DATABASE_URL", "")

    start = time.monotonic()
    sse_event = build_sse_event(
        session_id=session_id,
        step="retrieval_decision",
        status="completed",
        data={
            "routing_decision": ROUTING_DECISION,
            "confidence_score": _extract_confidence_score(step_input),
        },
    )

    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="retrieval_decision",
        status="completed",
        latency_ms=latency_ms,
    )

    return StepOutput(content=sse_event_to_json(sse_event))


def _extract_confidence_score(step_input: StepInput) -> float:
    """Extract confidence_score from the cag_match step's SSE event content.

    Falls back to 0.0 if the cag_match output is unavailable or malformed.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        The confidence_score from cag_match, or 0.0.
    """
    cag_content = step_input.get_step_content("cag_match")
    if cag_content is None:
        return 0.0

    try:
        event = json.loads(cag_content)
        return float(event.get("data", {}).get("confidence_score", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return 0.0
