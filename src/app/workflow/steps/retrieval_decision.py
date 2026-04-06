"""Step 3: retrieval_decision — routes workflow based on CAG confidence score.

Implements the Agno Condition node evaluator defined in DESIGN.md section 6.

Threshold:
    confidence_score >= 0.78  →  evaluator returns False  →  skip rag_retrieve
    confidence_score <  0.78  →  evaluator returns True   →  run  rag_retrieve

The branch decision is written to the SSE event ``data`` field.
"""

import json

from agno.workflow.types import StepInput

from app.workflow.sse import build_sse_event, sse_event_to_json

RETRIEVAL_CONFIDENCE_THRESHOLD = 0.78


def retrieval_decision_evaluator(step_input: StepInput) -> bool:
    """Route the workflow based on CAG confidence score.

    Reads ``confidence_score`` from the cag_match step output, compares it
    against the 0.78 threshold defined in DESIGN.md, and returns:

        True  → execute rag_retrieve (low confidence, retrieval needed)
        False → skip rag_retrieve, proceed directly to generate

    Emits an SSE event with the routing decision in the ``data`` field.

    Args:
        step_input: Agno step input carrying previous step outputs and
                    session metadata in ``additional_data``.

    Returns:
        True when retrieval is needed (confidence_score < 0.78).
        False when confidence is high enough to skip retrieval.
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    confidence_score = _extract_confidence_score(step_input)
    needs_retrieval = confidence_score < RETRIEVAL_CONFIDENCE_THRESHOLD

    routing_decision = "rag_retrieve" if needs_retrieval else "generate"

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

    # Side-effect: print the SSE event so it is visible during tests.
    # The FastAPI layer (feat/fastapi-service) will stream these events via SSE.
    print(sse_event_to_json(sse_event))

    return needs_retrieval


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
