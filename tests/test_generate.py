"""feat/generate merge checklist tests.

Verifies:
  - generate_executor and template_resolver are importable
  - prompt template is fetched from DB by template_key + is_active=True (never hardcoded)
  - prompt_template_version written to workflow state after step 5
  - raw_llm_output present in workflow state after step 5
  - SSE event structure matches DESIGN.md section 9
  - template key selection: confidence >= 0.85 → high_confidence_minimal_context
  - template key selection: confidence < 0.85  → low_confidence_with_retrieval
  - _format_template only replaces identifier placeholders, leaves JSON braces intact
  - retrieved_context is empty string when rag_retrieve step was skipped
  - retrieved_context is populated when rag_retrieve step ran
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.workflow.llm_usage import LLMResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sse_content(step: str, data: dict, session_id: str = "test-session") -> str:
    """Build the JSON string that a step executor writes to StepOutput.content."""
    return json.dumps(
        {
            "session_id": session_id,
            "step": step,
            "status": "completed",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "data": data,
            "error": None,
        }
    )


def _make_step_input(
    cag_data: dict | None = None,
    rag_data: dict | None = None,
    additional_data: dict | None = None,
    session_id: str = "test-session",
):
    """Build a StepInput with optional fake previous step outputs.

    Intake fields (destination, trip_length, budget, travel_style) are
    supplied directly via additional_data, matching how the API layer works.
    """
    from agno.workflow.types import StepInput, StepOutput

    base_additional = {
        "session_id": session_id,
        "destination": "sydney",
        "trip_length": 5,
        "budget": "moderate",
        "travel_style": "family",
    }
    if additional_data:
        base_additional.update(additional_data)

    previous_outputs: dict = {}

    if cag_data is not None:
        previous_outputs["cag_match"] = StepOutput(
            step_name="cag_match",
            content=_make_sse_content("cag_match", cag_data, session_id),
        )

    if rag_data is not None:
        previous_outputs["rag_retrieve"] = StepOutput(
            step_name="rag_retrieve",
            content=_make_sse_content("rag_retrieve", rag_data, session_id),
        )

    return StepInput(
        additional_data=base_additional,
        previous_step_outputs=previous_outputs if previous_outputs else None,
    )


def _make_fake_template(template_key: str, version: int = 1) -> MagicMock:
    """Create a mock PromptTemplate ORM object."""
    mock = MagicMock()
    mock.template_key = template_key
    mock.version = version
    mock.template_text = (
        "Plan a {trip_length}-day trip to {destination}. "
        "Style: {matched_category}. Tone: {tone}. "
        "Constraints: {constraints}. Context: {retrieved_context}."
    )
    mock.is_active = True
    return mock


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


def test_generate_executor_importable():
    from app.workflow.steps.generate import generate_executor  # noqa: F401


def test_template_resolver_importable():
    from app.workflow.template_resolver import TemplateNotFoundError, resolve_template  # noqa: F401


# ---------------------------------------------------------------------------
# Template key selection (unit tests — no DB or LLM needed)
# ---------------------------------------------------------------------------


def test_select_template_key_high_confidence():
    """confidence_score >= 0.85 must select high_confidence_minimal_context."""
    from app.workflow.steps.generate import (
        HIGH_CONFIDENCE_TEMPLATE_KEY,
        _select_template_key,
    )

    assert _select_template_key(0.85) == HIGH_CONFIDENCE_TEMPLATE_KEY
    assert _select_template_key(0.90) == HIGH_CONFIDENCE_TEMPLATE_KEY
    assert _select_template_key(1.00) == HIGH_CONFIDENCE_TEMPLATE_KEY


def test_select_template_key_low_confidence():
    """confidence_score < 0.85 must select low_confidence_with_retrieval."""
    from app.workflow.steps.generate import (
        LOW_CONFIDENCE_TEMPLATE_KEY,
        _select_template_key,
    )

    assert _select_template_key(0.77) == LOW_CONFIDENCE_TEMPLATE_KEY
    assert _select_template_key(0.50) == LOW_CONFIDENCE_TEMPLATE_KEY
    assert _select_template_key(0.00) == LOW_CONFIDENCE_TEMPLATE_KEY


def test_threshold_is_0_85():
    """RETRIEVAL_CONFIDENCE_THRESHOLD must equal 0.85."""
    from app.workflow.steps.generate import RETRIEVAL_CONFIDENCE_THRESHOLD

    assert RETRIEVAL_CONFIDENCE_THRESHOLD == 0.85


# ---------------------------------------------------------------------------
# _format_template unit tests
# ---------------------------------------------------------------------------


def test_format_template_replaces_known_variables():
    """_format_template substitutes all known {variable} placeholders."""
    from app.workflow.steps.generate import _format_template

    template = "Trip to {destination} for {trip_length} days, budget: {budget}."
    result = _format_template(template, {"destination": "Sydney", "trip_length": "5", "budget": "moderate"})

    assert "Sydney" in result
    assert "5 days" in result
    assert "moderate" in result


def test_format_template_leaves_json_braces_intact():
    """_format_template must NOT touch literal { } that form JSON structures."""
    from app.workflow.steps.generate import _format_template

    # Simulates the JSON schema example block present in both seed templates
    template = 'Go to {destination}.\nResult:\n{\n  "key": value\n}'
    result = _format_template(template, {"destination": "Melbourne"})

    assert "Melbourne" in result
    assert '{\n  "key": value\n}' in result


def test_format_template_leaves_unknown_placeholders_intact():
    """Unknown {placeholder} tokens are left unchanged (no KeyError raised)."""
    from app.workflow.steps.generate import _format_template

    template = "Hello {unknown_var} and {destination}."
    result = _format_template(template, {"destination": "Brisbane"})

    assert "{unknown_var}" in result
    assert "Brisbane" in result


def test_format_template_handles_empty_retrieved_context():
    """Empty retrieved_context string is substituted without error."""
    from app.workflow.steps.generate import _format_template

    template = "Context:\n{retrieved_context}\nEnd."
    result = _format_template(template, {"retrieved_context": ""})

    assert "Context:\n\nEnd." == result


# ---------------------------------------------------------------------------
# _extract_retrieved_context unit tests
# ---------------------------------------------------------------------------


def test_extract_retrieved_context_returns_empty_when_step_skipped():
    """Returns empty string when rag_retrieve step was not executed."""
    from app.workflow.steps.generate import _extract_retrieved_context

    step_input = _make_step_input(cag_data={"matched_category": "family", "confidence_score": 0.85})
    # No rag_data → rag_retrieve step output absent

    result = _extract_retrieved_context(step_input)

    assert result == ""


def test_extract_retrieved_context_returns_formatted_chunks():
    """Returns joined chunk text when rag_retrieve step provided results."""
    from app.workflow.steps.generate import _extract_retrieved_context

    rag_data = {
        "retrieved_context": [
            {"destination": "Sydney", "title": "Guide to Sydney", "chunk_text": "Sydney has great beaches."},
            {"destination": "Sydney", "title": "Sydney Transport", "chunk_text": "Trains run frequently."},
        ],
        "chunks_retrieved": 2,
    }
    step_input = _make_step_input(rag_data=rag_data)

    result = _extract_retrieved_context(step_input)

    assert "Sydney has great beaches." in result
    assert "Trains run frequently." in result
    assert "Guide to Sydney" in result


def test_extract_retrieved_context_returns_empty_for_empty_list():
    """Returns empty string when rag_retrieve ran but found no chunks."""
    from app.workflow.steps.generate import _extract_retrieved_context

    step_input = _make_step_input(rag_data={"retrieved_context": [], "chunks_retrieved": 0})

    result = _extract_retrieved_context(step_input)

    assert result == ""


# ---------------------------------------------------------------------------
# generate_executor integration (DB + LLM mocked)
# ---------------------------------------------------------------------------


def _run_generate_executor(
    confidence_score: float = 0.85,
    has_rag_context: bool = False,
    session_id: str = "test-session",
    llm_output: str = '{"destination": "Sydney", "trip_length_days": 5}',
):
    """Run generate_executor with DB and LLM fully mocked."""
    from app.workflow.steps.generate import generate_executor

    cag_data = {
        "matched_category": "family",
        "confidence_score": confidence_score,
        "tone": "friendly and family-oriented",
        "constraints": "Keep activities safe.",
    }

    rag_data = None
    if has_rag_context:
        rag_data = {
            "retrieved_context": [
                {"destination": "Sydney", "title": "Guide to Sydney", "chunk_text": "Bondi Beach is great."},
            ],
            "chunks_retrieved": 1,
        }

    step_input = _make_step_input(cag_data=cag_data, rag_data=rag_data, session_id=session_id)

    fake_template = _make_fake_template("high_confidence_minimal_context", version=1)

    with (
        patch("app.workflow.steps.generate.resolve_template", return_value=(fake_template.template_text, 1)),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult(llm_output)),
        patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql://fake",
                "GEMINI_API_KEY": "fake-key",
                "LLM_MODEL": "gemini-3.1-flash-lite",
            },
        ),
    ):
        output = generate_executor(step_input)

    return json.loads(output.content)


def test_raw_llm_output_present_in_workflow_state():
    """Checklist: raw_llm_output must be present in workflow state after step 5."""
    event = _run_generate_executor(llm_output='{"destination": "Sydney"}')

    assert "raw_llm_output" in event["data"]
    assert event["data"]["raw_llm_output"] == '{"destination": "Sydney"}'


def test_prompt_template_version_written_to_workflow_state():
    """Checklist: prompt_template_version must be written to workflow state after step 5."""
    event = _run_generate_executor()

    assert "prompt_template_version" in event["data"]
    assert event["data"]["prompt_template_version"] == 1


def test_prompt_template_key_written_to_workflow_state():
    """prompt_template_key must be written to workflow state for observability."""
    event = _run_generate_executor(confidence_score=0.85)

    assert "prompt_template_key" in event["data"]


def test_sse_event_step_is_generate():
    """SSE event step field must be 'generate'."""
    event = _run_generate_executor()

    assert event["step"] == "generate"


def test_sse_event_status_is_completed():
    """SSE event status must be 'completed' on success."""
    event = _run_generate_executor()

    assert event["status"] == "completed"


def test_sse_event_session_id_propagated():
    """SSE event session_id must match the request session_id."""
    event = _run_generate_executor(session_id="my-session-123")

    assert event["session_id"] == "my-session-123"


def test_sse_event_structure():
    """SSE event must include all required fields from DESIGN.md section 9."""
    event = _run_generate_executor()

    for field in ("session_id", "step", "status", "timestamp", "data", "error"):
        assert field in event, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Template key routing in generate_executor
# ---------------------------------------------------------------------------


def test_high_confidence_uses_minimal_context_template():
    """confidence_score >= 0.85 must resolve high_confidence_minimal_context template."""
    from app.workflow.steps.generate import (
        HIGH_CONFIDENCE_TEMPLATE_KEY,
        generate_executor,
    )

    step_input = _make_step_input(cag_data={"matched_category": "family", "confidence_score": 0.85, "tone": "friendly", "constraints": "safe"})

    captured_key = {}

    def fake_resolve(template_key, db_url, version=None):
        captured_key["key"] = template_key
        return ("Plan a trip to {destination}.", 1)

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult("some output")),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        generate_executor(step_input)

    assert captured_key["key"] == HIGH_CONFIDENCE_TEMPLATE_KEY


def test_low_confidence_uses_retrieval_template():
    """confidence_score < 0.85 must resolve low_confidence_with_retrieval template."""
    from app.workflow.steps.generate import (
        LOW_CONFIDENCE_TEMPLATE_KEY,
        generate_executor,
    )

    step_input = _make_step_input(cag_data={"matched_category": "family", "confidence_score": 0.50, "tone": "friendly", "constraints": "safe"})

    captured_key = {}

    def fake_resolve(template_key, db_url, version=None):
        captured_key["key"] = template_key
        return ("Plan a trip to {destination}. Context: {retrieved_context}.", 1)

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult("some output")),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        generate_executor(step_input)

    assert captured_key["key"] == LOW_CONFIDENCE_TEMPLATE_KEY


def test_template_never_hardcoded_resolve_template_always_called():
    """Checklist: resolve_template must be called — template text never hardcoded."""
    from app.workflow.steps.generate import generate_executor

    step_input = _make_step_input(cag_data={"matched_category": "family", "confidence_score": 0.85, "tone": "t", "constraints": "c"})

    resolve_called = {"called": False}

    def fake_resolve(template_key, db_url, version=None):
        resolve_called["called"] = True
        return ("Trip to {destination}.", 1)

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult("output")),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        generate_executor(step_input)

    assert resolve_called["called"], "resolve_template was not called — template may be hardcoded"


# ---------------------------------------------------------------------------
# template_resolver unit tests (DB mocked via SQLAlchemy session)
# ---------------------------------------------------------------------------


def test_resolve_template_returns_text_and_version():
    """resolve_template returns (template_text, version) for an active template."""
    from app.workflow.template_resolver import resolve_template

    mock_template = MagicMock()
    mock_template.template_text = "Plan a trip to {destination}."
    mock_template.version = 2

    with patch("app.workflow.template_resolver.create_engine"), patch(
        "app.workflow.template_resolver.Session"
    ) as MockSession:
        MockSession.return_value.__enter__.return_value.scalar.return_value = mock_template

        text, version = resolve_template(
            template_key="high_confidence_minimal_context",
            db_url="postgresql://fake",
        )

    assert text == "Plan a trip to {destination}."
    assert version == 2


def test_resolve_template_raises_when_not_found():
    """resolve_template raises TemplateNotFoundError when no active template exists."""
    from app.workflow.template_resolver import TemplateNotFoundError, resolve_template

    with patch("app.workflow.template_resolver.create_engine"), patch(
        "app.workflow.template_resolver.Session"
    ) as MockSession:
        MockSession.return_value.__enter__.return_value.scalar.return_value = None

        with pytest.raises(TemplateNotFoundError):
            resolve_template(
                template_key="nonexistent_key",
                db_url="postgresql://fake",
            )


def test_resolve_template_with_version_override_returns_that_version():
    """When version is supplied, resolve_template returns that specific version."""
    from app.workflow.template_resolver import resolve_template

    mock_template = MagicMock()
    mock_template.template_text = "Version 3 template."
    mock_template.version = 3

    with patch("app.workflow.template_resolver.create_engine"), patch(
        "app.workflow.template_resolver.Session"
    ) as MockSession:
        MockSession.return_value.__enter__.return_value.scalar.return_value = mock_template

        text, version = resolve_template(
            template_key="high_confidence_minimal_context",
            db_url="postgresql://fake",
            version=3,
        )

    assert text == "Version 3 template."
    assert version == 3


def test_resolve_template_version_override_raises_when_not_found():
    """Requesting a non-existent specific version raises TemplateNotFoundError."""
    from app.workflow.template_resolver import TemplateNotFoundError, resolve_template

    with patch("app.workflow.template_resolver.create_engine"), patch(
        "app.workflow.template_resolver.Session"
    ) as MockSession:
        MockSession.return_value.__enter__.return_value.scalar.return_value = None

        with pytest.raises(TemplateNotFoundError):
            resolve_template(
                template_key="high_confidence_minimal_context",
                db_url="postgresql://fake",
                version=99,
            )


def test_generate_executor_passes_version_override_to_resolve_template():
    """When template_version is in additional_data, it is forwarded to resolve_template."""
    from app.workflow.steps.generate import generate_executor

    resolve_calls = []

    def fake_resolve(template_key, db_url, version=None):
        resolve_calls.append(version)
        return ("Plan a trip to {destination}.", 5)

    step_input = _make_step_input(
        cag_data={"matched_category": "family", "confidence_score": 0.90},
        additional_data={"template_version": 5},
    )

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult('{"ok": true}')),
        patch("app.workflow.steps.generate.write_trace"),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "k"}),
    ):
        generate_executor(step_input)

    assert resolve_calls, "resolve_template was never called"
    assert resolve_calls[0] == 5, (
        f"Expected version=5 forwarded to resolve_template, got {resolve_calls[0]!r}"
    )


def test_generate_executor_no_version_override_passes_none_to_resolve_template():
    """When template_version is absent, resolve_template receives version=None."""
    from app.workflow.steps.generate import generate_executor

    resolve_calls = []

    def fake_resolve(template_key, db_url, version=None):
        resolve_calls.append(version)
        return ("Plan a trip to {destination}.", 1)

    step_input = _make_step_input(
        cag_data={"matched_category": "family", "confidence_score": 0.90},
    )

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult('{"ok": true}')),
        patch("app.workflow.steps.generate.write_trace"),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "k"}),
    ):
        generate_executor(step_input)

    assert resolve_calls, "resolve_template was never called"
    assert resolve_calls[0] is None, (
        f"Expected version=None when no override, got {resolve_calls[0]!r}"
    )
