"""Step 4: rag_retrieve — retrieves top-k relevant source document chunks.

Executed only when ``retrieval_decision`` routes to the retrieval path
(confidence_score < 0.78).

Embeds the user's travel query using the same Gemini model as the seed
script and performs a cosine similarity search against
``source_documents.embedding_vector`` via pgvector.

Writes ``retrieved_context`` (a list of chunk dicts) to the SSE event
``data`` field so the ``generate`` step can inject it into the prompt.

Graceful degradation: if the pgvector query or embedding call raises an
exception, the error is logged and the step continues with an empty
``retrieved_context`` list — the workflow never crashes here.
"""

import json
import logging
import os
import time

from agno.workflow.types import StepInput, StepOutput

from app.workflow.retrieval_service import retrieve_documents
from app.workflow.sse import build_sse_event, sse_event_to_json
from app.workflow.trace_logger import write_trace

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5


def _build_query_text(step_input: StepInput) -> str:
    """Construct a retrieval query from intake and cag_match step outputs.

    Reads ``destination`` and ``travel_style`` from the intake SSE event and
    ``matched_category`` from the cag_match SSE event to form a targeted
    retrieval query.  Falls back to using just the destination if earlier step
    outputs are unavailable.

    Args:
        step_input: Agno step input carrying previous step outputs.

    Returns:
        A free-text query string for the pgvector similarity search.
    """
    destination = _extract_field_from_step(step_input, "intake", "destination")
    travel_style = _extract_field_from_step(step_input, "intake", "travel_style")
    matched_category = _extract_field_from_step(step_input, "cag_match", "matched_category")

    parts = []
    if travel_style:
        parts.append(travel_style)
    parts.append(f"travel in {destination}" if destination else "travel in Australia")
    if matched_category:
        parts.append(f"{matched_category} itinerary")

    return " ".join(parts)


def _extract_field_from_step(step_input: StepInput, step_name: str, field: str) -> str:
    """Extract a single field from a previous step's SSE event data.

    Args:
        step_input: Agno step input carrying previous step outputs.
        step_name:  Name of the step whose output to read (e.g. ``"intake"``).
        field:      Key to extract from the SSE event ``data`` dict.

    Returns:
        The string value, or an empty string if unavailable or malformed.
    """
    content = step_input.get_step_content(step_name)
    if content is None:
        return ""
    try:
        event = json.loads(content)
        return str(event.get("data", {}).get(field, ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def rag_retrieve_executor(step_input: StepInput) -> StepOutput:
    """Retrieve top-k source document chunks relevant to the user's travel query.

    Reads normalised input fields from the ``intake`` step and the matched
    category from the ``cag_match`` step to build a targeted retrieval query.
    Performs a pgvector cosine similarity search against ``source_documents``
    and writes the results to the SSE event ``data`` field as
    ``retrieved_context``.

    If the embedding call or DB query fails, the error is logged and the step
    completes with an empty ``retrieved_context`` list — the workflow
    continues without crashing.

    Args:
        step_input: Agno step input carrying previous step outputs and
                    session metadata in ``additional_data``.

    Returns:
        A :class:`StepOutput` whose ``content`` is a JSON-serialised SSE event
        with ``retrieved_context`` in the ``data`` field.
    """
    additional_data: dict = step_input.additional_data or {}
    session_id: str = additional_data.get("session_id", "unknown")

    db_url: str = os.environ["DATABASE_URL"]
    api_key: str = os.environ["GEMINI_API_KEY"]
    embedding_model: str = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")

    start = time.monotonic()
    query_text = _build_query_text(step_input)

    try:
        chunks = retrieve_documents(
            query_text=query_text,
            db_url=db_url,
            api_key=api_key,
            embedding_model=embedding_model,
            top_k=DEFAULT_TOP_K,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "rag_retrieve: unexpected error from retrieval service — continuing with empty context. "
            "Error: %s",
            exc,
        )
        chunks = []

    retrieved_context = [
        {
            "destination": chunk.destination,
            "title": chunk.title,
            "chunk_text": chunk.chunk_text,
        }
        for chunk in chunks
    ]

    sse_event = build_sse_event(
        session_id=session_id,
        step="rag_retrieve",
        status="completed",
        data={
            "retrieved_context": retrieved_context,
            "chunks_retrieved": len(retrieved_context),
            "query_text": query_text,
        },
    )

    latency_ms = (time.monotonic() - start) * 1000
    write_trace(
        db_url=db_url,
        session_id=session_id,
        step_name="rag_retrieve",
        status="completed",
        latency_ms=latency_ms,
    )

    return StepOutput(content=sse_event_to_json(sse_event))
