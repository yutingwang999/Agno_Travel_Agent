"""Step 4: rag_retrieve — stub implementation.

Accepts workflow state, emits an SSE event, returns state unchanged.
Executed only when retrieval_decision routes to the retrieval path.
Business logic will be filled in by feat/rag-retrieve.
"""

from agno.workflow.types import StepInput, StepOutput

from app.workflow.sse import build_sse_event, sse_event_to_json


def rag_retrieve_executor(step_input: StepInput) -> StepOutput:
    """Stub for the rag_retrieve step.

    Retrieves top-k relevant documents from pgvector (not yet implemented).
    Emits an SSE event and passes state through unchanged.
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    sse_event = build_sse_event(
        session_id=session_id,
        step="rag_retrieve",
        status="completed",
    )

    return StepOutput(content=sse_event_to_json(sse_event))
