"""Step 3: retrieval_decision — stub condition evaluator.

Used as the evaluator for the Agno Condition node.
Emits an SSE event and returns True (meaning rag_retrieve will run)
as a stub until feat/retrieval-decision fills in the real threshold logic.

Final logic (feat/retrieval-decision):
    confidence_score >= 0.78  →  evaluator returns False  →  skip rag_retrieve
    confidence_score <  0.78  →  evaluator returns True   →  run  rag_retrieve
"""

from agno.workflow.types import StepInput

from app.workflow.sse import build_sse_event, sse_event_to_json


def retrieval_decision_evaluator(step_input: StepInput) -> bool:
    """Stub evaluator for the retrieval_decision Condition node.

    Always returns True so the rag_retrieve branch runs in skeleton tests,
    producing one SSE event per step (6 total).
    """
    session_id: str = (step_input.additional_data or {}).get("session_id", "unknown")

    sse_event = build_sse_event(
        session_id=session_id,
        step="retrieval_decision",
        status="completed",
        data={"routing_decision": "rag_retrieve"},
    )

    # Side-effect: print the SSE event so it is visible during skeleton tests.
    # The FastAPI layer (feat/fastapi-service) will stream these events via SSE.
    print(sse_event_to_json(sse_event))

    # Stub: always take the rag_retrieve branch.
    return True
