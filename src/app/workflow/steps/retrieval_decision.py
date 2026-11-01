"""Step 3: retrieval_decision — routes workflow based on CAG confidence score.

A plain Step that makes the routing decision and emits it as its SSE event,
followed by an Agno Condition (``retrieval_branch``) whose evaluator only reads
that decision back.  Splitting the two keeps the event on the same step-output
channel as every other step (no stdout side effect).

Threshold:
    confidence_score >= 0.85  →  routing_decision "generate"      →  skip rag_retrieve
    confidence_score <  0.85  →  routing_decision "rag_retrieve"  →  run  rag_retrieve

The branch decision is written to the SSE event ``data`` field.
"""

import json
import os
import time

from agno.workflow.types import StepInput, StepOutput

from app.workflow.config import RETRIEVAL_CONFIDENCE_THRESHOLD
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.trace_logger import write_trace


def retrieval_decision_executor(step_input: StepInput) -> StepOutput:
    """Decide whether rag_retrieve runs, based on the CAG confidence score.

    Reads ``confidence_score`` from the cag_match step output and compares it
    against the 0.85 threshold defined in DESIGN.md.

    Writes ``routing_decision`` (``"rag_retrieve"`` or ``"generate"``),
    ``confidence_score`` and ``threshold`` to the SSE event ``data`` field;
    :func:`needs_retrieval` reads ``routing_decision`` back for the Condition.

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

    confidence_score = _extract_confidence_score(step_input)
    routing_decision = (
        "rag_retrieve" if confidence_score < RETRIEVAL_CONFIDENCE_THRESHOLD else "generate"
    )

    sse_event = build_sse_event(
        session_id=session_id,
        step="retrieval_decision",
        status="completed",
        data={
            "routing_decision": routing_decision,
            "confidence_score": confidence_score,
            "threshold": RETRIEVAL_CONFIDENCE_THRESHOLD,
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


def needs_retrieval(step_input: StepInput) -> bool:
    """Condition evaluator: True when the retrieval_decision step chose rag_retrieve.

    Has no side effects.  Falls back to True (run retrieval, the safe default)
    if the retrieval_decision output is unavailable or malformed.
    """
    content = step_input.get_step_content("retrieval_decision")
    if content is None:
        return True

    try:
        event = json.loads(content)
        return event.get("data", {}).get("routing_decision") != "generate"
    except (json.JSONDecodeError, TypeError, AttributeError):
        return True


def _extract_confidence_score(step_input: StepInput) -> float:
    """Extract confidence_score from the cag_match step's SSE event content.

    Falls back to 0.0 if the cag_match output is unavailable or malformed,
    which causes the retrieval branch to run (safe default).

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        The confidence_score from cag_match, or 0.0 as a safe fallback.
    """
    cag_content = step_input.get_step_content("cag_match")
    if cag_content is None:
        return 0.0

    try:
        event = json.loads(cag_content)
        return float(event.get("data", {}).get("confidence_score", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0
