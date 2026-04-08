"""feat/rag-retrieve merge checklist tests.

Verifies:
  - rag_retrieve_executor and retrieval_service are importable
  - SSE event for rag_retrieve is emitted regardless of whether results were found
  - workflow state contains a retrieved_context list with up to 5 items after step 4
  - if pgvector query raises an exception, workflow continues with empty retrieved_context
  - _build_query_text constructs a meaningful query from prior step outputs
  - _extract_field_from_step handles missing / malformed step outputs gracefully
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sse_content(step: str, data: dict) -> str:
    """Build the JSON string that a step executor writes to StepOutput.content."""
    return json.dumps(
        {
            "session_id": "test-session",
            "step": step,
            "status": "completed",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "data": data,
            "error": None,
        }
    )


def _make_step_input(
    intake_data: dict | None = None,
    cag_data: dict | None = None,
    session_id: str = "test-session",
):
    """Build a StepInput with optional fake intake and cag_match previous outputs."""
    from agno.workflow.types import StepInput, StepOutput

    additional_data = {"session_id": session_id}
    previous_outputs: dict = {}

    if intake_data is not None:
        previous_outputs["intake"] = StepOutput(
            step_name="intake",
            content=_make_sse_content("intake", intake_data),
        )

    if cag_data is not None:
        previous_outputs["cag_match"] = StepOutput(
            step_name="cag_match",
            content=_make_sse_content("cag_match", cag_data),
        )

    return StepInput(
        additional_data=additional_data,
        previous_step_outputs=previous_outputs if previous_outputs else None,
    )


def _make_fake_chunks(count: int = 3):
    """Return a list of fake RetrievedChunk instances."""
    from app.workflow.retrieval_service import RetrievedChunk

    return [
        RetrievedChunk(
            destination="Sydney",
            title=f"Chunk {i}",
            chunk_text=f"Some travel text about Sydney #{i}.",
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_rag_retrieve_executor_importable():
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor  # noqa: F401


def test_retrieval_service_importable():
    from app.workflow.retrieval_service import retrieve_documents  # noqa: F401


def test_retrieved_chunk_importable():
    from app.workflow.retrieval_service import RetrievedChunk  # noqa: F401


# ---------------------------------------------------------------------------
# SSE event always emitted
# ---------------------------------------------------------------------------


def test_sse_event_emitted_when_results_found():
    """Checklist: SSE event for rag_retrieve is emitted when chunks are returned."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    fake_chunks = _make_fake_chunks(3)
    step_input = _make_step_input(
        intake_data={"destination": "sydney", "travel_style": "family", "trip_length": 5, "budget": "moderate"},
        cag_data={"matched_category": "family", "confidence_score": 0.65},
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=fake_chunks),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    assert event["step"] == "rag_retrieve"
    assert event["status"] == "completed"


def test_sse_event_emitted_when_no_results():
    """Checklist: SSE event for rag_retrieve is emitted even when no chunks found."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    step_input = _make_step_input(
        intake_data={"destination": "alice springs", "travel_style": "adventure", "trip_length": 3, "budget": "budget"},
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=[]),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    assert event["step"] == "rag_retrieve"
    assert event["status"] == "completed"
    assert event["data"]["retrieved_context"] == []


# ---------------------------------------------------------------------------
# retrieved_context in workflow state
# ---------------------------------------------------------------------------


def test_retrieved_context_list_in_data():
    """Checklist: workflow state contains a retrieved_context list after step 4."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    fake_chunks = _make_fake_chunks(5)
    step_input = _make_step_input(
        intake_data={"destination": "melbourne", "travel_style": "budget", "trip_length": 7, "budget": "budget"},
        cag_data={"matched_category": "budget", "confidence_score": 0.60},
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=fake_chunks),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    retrieved_context = event["data"]["retrieved_context"]

    assert isinstance(retrieved_context, list)
    assert len(retrieved_context) == 5


def test_retrieved_context_respects_top_k_limit():
    """retrieve_documents is called with top_k=5, so at most 5 chunks are returned."""
    from app.workflow.steps.rag_retrieve import DEFAULT_TOP_K, rag_retrieve_executor

    assert DEFAULT_TOP_K == 5

    fake_chunks = _make_fake_chunks(5)
    step_input = _make_step_input(
        intake_data={"destination": "cairns", "travel_style": "adventure", "trip_length": 4, "budget": "moderate"},
    )

    captured_kwargs: dict = {}

    def fake_retrieve(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_chunks

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", side_effect=fake_retrieve),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        rag_retrieve_executor(step_input)

    assert captured_kwargs.get("top_k") == 5


def test_retrieved_context_chunk_fields():
    """Each item in retrieved_context must have destination, title, chunk_text."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    fake_chunks = _make_fake_chunks(2)
    step_input = _make_step_input(
        intake_data={"destination": "sydney", "travel_style": "family", "trip_length": 5, "budget": "moderate"},
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=fake_chunks),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    for item in event["data"]["retrieved_context"]:
        assert "destination" in item
        assert "title" in item
        assert "chunk_text" in item


# ---------------------------------------------------------------------------
# Graceful degradation — exception in retrieve_documents
# ---------------------------------------------------------------------------


def test_graceful_degradation_on_db_exception():
    """Checklist: if pgvector query raises an exception, workflow continues with empty context."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    step_input = _make_step_input(
        intake_data={"destination": "perth", "travel_style": "family", "trip_length": 5, "budget": "moderate"},
    )

    # retrieve_documents raises — step must not propagate the exception
    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", side_effect=RuntimeError("DB is down")),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    assert event["step"] == "rag_retrieve"
    assert event["data"]["retrieved_context"] == []


def test_retrieve_documents_returns_empty_list_on_exception():
    """retrieval_service.retrieve_documents returns [] when build_knowledge or search fails."""
    from app.workflow.retrieval_service import retrieve_documents

    with patch(
        "app.workflow.retrieval_service.build_knowledge",
        side_effect=ConnectionError("DB unreachable"),
    ):
        result = retrieve_documents(
            query_text="family trip in Sydney",
            db_url="postgresql://fake",
            api_key="fake-key",
        )

    assert result == []


# ---------------------------------------------------------------------------
# SSE event structure
# ---------------------------------------------------------------------------


def test_sse_event_structure():
    """SSE event must include session_id, step, status, timestamp, data, error."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    step_input = _make_step_input(
        intake_data={"destination": "brisbane", "travel_style": "budget", "trip_length": 3, "budget": "budget"},
        session_id="abc-123",
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=[]),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    assert event["session_id"] == "abc-123"
    assert event["step"] == "rag_retrieve"
    assert event["status"] == "completed"
    assert "timestamp" in event
    assert "data" in event
    assert "error" in event


def test_sse_event_data_includes_chunks_retrieved_count():
    """SSE event data must include chunks_retrieved count for observability."""
    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    fake_chunks = _make_fake_chunks(3)
    step_input = _make_step_input(
        intake_data={"destination": "hobart", "travel_style": "adventure", "trip_length": 4, "budget": "moderate"},
    )

    with (
        patch("app.workflow.steps.rag_retrieve.retrieve_documents", return_value=fake_chunks),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        output = rag_retrieve_executor(step_input)

    event = json.loads(output.content)
    assert event["data"]["chunks_retrieved"] == 3


# ---------------------------------------------------------------------------
# _build_query_text unit tests
# ---------------------------------------------------------------------------


def test_build_query_text_uses_destination_and_style():
    """_build_query_text incorporates destination and travel_style from intake."""
    from app.workflow.steps.rag_retrieve import _build_query_text

    step_input = _make_step_input(
        intake_data={"destination": "sydney", "travel_style": "family", "trip_length": 5, "budget": "moderate"},
        cag_data={"matched_category": "family", "confidence_score": 0.65},
    )

    query = _build_query_text(step_input)

    assert "sydney" in query.lower()
    assert "family" in query.lower()


def test_build_query_text_fallback_when_no_prior_outputs():
    """_build_query_text falls back gracefully when intake output is missing."""
    from app.workflow.steps.rag_retrieve import _build_query_text

    from agno.workflow.types import StepInput

    step_input = StepInput(additional_data={"session_id": "test"})
    query = _build_query_text(step_input)

    # Must produce some non-empty string — does not crash
    assert isinstance(query, str)
    assert len(query) > 0


# ---------------------------------------------------------------------------
# _extract_field_from_step unit tests
# ---------------------------------------------------------------------------


def test_extract_field_returns_correct_value():
    """_extract_field_from_step returns the field value from SSE event data."""
    from app.workflow.steps.rag_retrieve import _extract_field_from_step

    step_input = _make_step_input(
        intake_data={"destination": "sydney", "travel_style": "family", "trip_length": 5, "budget": "moderate"},
    )

    assert _extract_field_from_step(step_input, "intake", "destination") == "sydney"
    assert _extract_field_from_step(step_input, "intake", "travel_style") == "family"


def test_extract_field_returns_empty_string_when_step_missing():
    """_extract_field_from_step returns '' when the step has no output."""
    from app.workflow.steps.rag_retrieve import _extract_field_from_step

    from agno.workflow.types import StepInput

    step_input = StepInput(additional_data={"session_id": "test"})
    result = _extract_field_from_step(step_input, "intake", "destination")

    assert result == ""


def test_extract_field_returns_empty_string_on_malformed_json():
    """_extract_field_from_step returns '' when the step output is malformed JSON."""
    from app.workflow.steps.rag_retrieve import _extract_field_from_step

    from agno.workflow.types import StepInput, StepOutput

    step_input = StepInput(
        additional_data={"session_id": "test"},
        previous_step_outputs={
            "intake": StepOutput(step_name="intake", content="not valid json {{{")
        },
    )
    result = _extract_field_from_step(step_input, "intake", "destination")

    assert result == ""
