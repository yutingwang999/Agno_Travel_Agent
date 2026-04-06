"""Step 2: cag_match — stub implementation.

Accepts workflow state, emits an SSE event, returns state unchanged.
Business logic will be filled in by feat/cag-match.
"""

from agno.workflow.types import StepInput, StepOutput

from app.workflow.sse import build_sse_event, sse_event_to_json


def cag_match_executor(step_input: StepInput) -> StepOutput:
    """Stub for the cag_match step.

    Maps free-text intent to a category using embeddings (not yet implemented).
    Emits an SSE event and passes state through unchanged.
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    sse_event = build_sse_event(
        session_id=session_id,
        step="cag_match",
        status="completed",
    )

    return StepOutput(content=sse_event_to_json(sse_event))
