"""Step 6: validate_output — stub implementation.

Accepts workflow state, emits an SSE event, returns state unchanged.
Business logic will be filled in by feat/validate-output.
"""

from agno.workflow.types import StepInput, StepOutput

from app.workflow.sse import build_sse_event, sse_event_to_json


def validate_output_executor(step_input: StepInput) -> StepOutput:
    """Stub for the validate_output step.

    Validates raw LLM output against a Pydantic schema and retries on failure
    (not yet implemented). Emits an SSE event and passes state through unchanged.
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    sse_event = build_sse_event(
        session_id=session_id,
        step="validate_output",
        status="completed",
    )

    return StepOutput(content=sse_event_to_json(sse_event))
