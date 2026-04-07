"""Step 2: cag_match — maps free-text intent to an itinerary category.

Embeds the user's travel intent using the same Gemini embedding model as the
seed script (gemini-embedding-001, 768 dimensions), then performs a cosine
similarity search against ``itinerary_categories.embedding_vector`` via
pgvector.

Output written to SSE event ``data`` field:
    matched_category   — category_key of the best-matching category
    confidence_score   — cosine similarity score (0.0–1.0)
    tone               — tone string from the matched category row
    constraints        — constraints string from the matched category row
    is_fallback        — True when confidence was below the minimum threshold

Falls back to the default category when no match exceeds the minimum
similarity threshold defined in :mod:`app.workflow.cag_matcher`.
"""

import os
import time

from agno.workflow.types import StepInput, StepOutput

from app.workflow.cag_matcher import match_category
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.trace_logger import write_trace


def _build_intent_text(additional_data: dict) -> str:
    """Construct a free-text travel intent string from normalised request fields."""
    travel_style = additional_data.get("travel_style", "")
    destination = additional_data.get("destination", "")
    budget = additional_data.get("budget", "")
    return f"{travel_style} trip to {destination} with {budget} budget"


def cag_match_executor(step_input: StepInput) -> StepOutput:
    """Embed user intent and find the closest itinerary category.

    Reads the normalised travel planning fields from
    ``step_input.additional_data``, builds a free-text intent string, embeds
    it with the Gemini API (gemini-embedding-001), and performs a cosine
    similarity search against ``itinerary_categories``.

    Writes ``matched_category`` and ``confidence_score`` (plus ``tone`` and
    ``constraints``) to the SSE event ``data`` field for downstream steps.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")

    db_url: str = os.environ["DATABASE_URL"]
    api_key: str = os.environ["GEMINI_API_KEY"]
    embedding_model: str = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")

    start = time.monotonic()

    intent_text = _build_intent_text(additional_data)

    result = match_category(
        intent_text=intent_text,
        db_url=db_url,
        api_key=api_key,
        embedding_model=embedding_model,
    )

    sse_event = build_sse_event(
        session_id=session_id,
        step="cag_match",
        status="completed",
        data={
            "matched_category": result.category_key,
            "confidence_score": result.confidence_score,
            "tone": result.tone,
            "constraints": result.constraints,
            "is_fallback": result.is_fallback,
        },
    )

    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="cag_match",
        status="completed",
        latency_ms=latency_ms,
    )

    return StepOutput(content=sse_event_to_json(sse_event))
