"""Step 1: intake — stub implementation.

Accepts workflow state, emits an SSE event, returns state unchanged.
Business logic will be filled in by feat/intake.
"""

from agno.workflow.types import StepInput, StepOutput

from app.workflow.sse import build_sse_event, sse_event_to_json


def intake_executor(step_input: StepInput) -> StepOutput:
    """Stub for the intake step.

    Validates and normalises user input (not yet implemented).
    Emits an SSE event and passes state through unchanged.
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    sse_event = build_sse_event(
        session_id=session_id,
        step="intake",
        status="completed",
    )

    return StepOutput(content=sse_event_to_json(sse_event))
