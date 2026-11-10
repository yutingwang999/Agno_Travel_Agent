"""feat/generate merge checklist tests.

Verifies:
  - generate_executor and template_resolver are importable
  - prompt template is fetched from DB by template_key + is_active=True (never hardcoded)
  - prompt_template_version written to workflow state after step 5
  - raw_llm_output present in workflow state after step 5
  - SSE event structure matches DESIGN.md section 9
  - every request uses itinerary_with_context, whatever the confidence (rebuild-rag)
  - {notes} is substituted, and empty when the request has none
  - _format_template only replaces identifier placeholders, leaves JSON braces intact
  - retrieved chunks are numbered [S1], [S2], ... and listed in context_sources (rebuild-rag)
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
# Single template key (rebuild-rag)
# ---------------------------------------------------------------------------


def test_template_key_is_itinerary_with_context():
    from app.workflow.steps.generate import TEMPLATE_KEY

    assert TEMPLATE_KEY == "itinerary_with_context"


def test_confidence_based_selection_is_gone():
    import app.workflow.steps.generate as generate

    for name in ("RETRIEVAL_CONFIDENCE_THRESHOLD", "HIGH_CONFIDENCE_TEMPLATE_KEY",
                 "LOW_CONFIDENCE_TEMPLATE_KEY", "_select_template_key"):
        assert not hasattr(generate, name), name


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


def _chunk(n: int) -> dict:
    return {"chunk_id": f"c{n}", "destination": "sydney", "state": "NSW", "title": f"Title {n}",
            "chunk_text": f"Text {n}.", "source": f"https://example.org/{n}", "section": "Do"}


def test_citation_ids_assigned():
    """Spec scenario "Citation ids assigned": blocks start with [S1], [S2], [S3] in retrieval order."""
    from app.workflow.steps.generate import _extract_retrieved_context

    rendered, _ = _extract_retrieved_context(_make_step_input(rag_data={"retrieved_context": [_chunk(1), _chunk(2), _chunk(3)]}))

    assert rendered == "[S1] Title 1\nText 1.\n\n[S2] Title 2\nText 2.\n\n[S3] Title 3\nText 3."


@pytest.mark.parametrize("rag_data", [None, {"retrieved_context": [], "chunks_retrieved": 0}])
def test_retrieval_returned_nothing(rag_data):
    """Spec scenarios "Retrieval returned nothing" and "No chunks retrieved"."""
    from app.workflow.steps.generate import _extract_retrieved_context

    assert _extract_retrieved_context(_make_step_input(rag_data=rag_data)) == ("", [])


def test_sources_listed():
    """Spec scenario "Sources listed": one context_sources entry per chunk in the prompt."""
    from app.workflow.steps.generate import _extract_retrieved_context

    _, sources = _extract_retrieved_context(_make_step_input(rag_data={"retrieved_context": [_chunk(1), _chunk(2), _chunk(3)]}))

    assert [s["id"] for s in sources] == ["S1", "S2", "S3"]
    assert sources[1] == {"id": "S2", "chunk_id": "c2", "title": "Title 2",
                          "source": "https://example.org/2", "section": "Do"}


def test_generate_event_carries_context_sources():
    event = _run_generate_executor(has_rag_context=True)

    assert [s["id"] for s in event["data"]["context_sources"]] == ["S1"]


def test_generate_event_has_empty_context_sources_without_chunks():
    event = _run_generate_executor(has_rag_context=False)

    assert event["data"]["context_sources"] == []


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


@pytest.mark.parametrize("confidence_score", [0.95, 0.20])
def test_any_confidence_uses_itinerary_with_context(confidence_score):
    """Spec scenario "Any confidence"."""
    from app.workflow.steps.generate import generate_executor

    step_input = _make_step_input(cag_data={"matched_category": "family", "confidence_score": confidence_score, "tone": "friendly", "constraints": "safe"})

    captured_keys = []

    def fake_resolve(template_key, db_url, version=None):
        captured_keys.append(template_key)
        return ("Plan a trip to {destination}. Context: {retrieved_context}.", 1)

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=fake_resolve),
        patch("app.workflow.steps.generate._call_llm", return_value=LLMResult("some output")),
        patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "fake-key"}),
    ):
        event = json.loads(generate_executor(step_input).content)

    assert captured_keys == ["itinerary_with_context"]
    assert event["data"]["prompt_template_key"] == "itinerary_with_context"


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


# ---------------------------------------------------------------------------
# Template fallback and LLM failure (harden-workflow-guardrails)
# ---------------------------------------------------------------------------

_ENV = {"DATABASE_URL": "postgresql://fake", "GEMINI_API_KEY": "k"}
_CAG = {"matched_category": "family", "confidence_score": 0.90, "tone": "friendly", "constraints": ""}


def test_template_table_empty_names_selected_key_and_skips_llm():
    """Spec scenario "Template table empty": error event naming the key, no fallback, LLM not called."""
    from app.workflow.steps.generate import generate_executor
    from app.workflow.template_resolver import TemplateNotFoundError

    with (
        patch("app.workflow.steps.generate.resolve_template", side_effect=TemplateNotFoundError("x")) as mock_resolve,
        patch("app.workflow.steps.generate._call_llm") as mock_llm,
        patch("app.workflow.steps.generate.write_trace") as mock_trace,
        patch.dict("os.environ", _ENV),
    ):
        event = json.loads(generate_executor(_make_step_input(cag_data=_CAG)).content)

    assert event["status"] == "error"
    assert event["error"] == "No active template found for key 'itinerary_with_context'"
    assert mock_resolve.call_count == 1
    mock_llm.assert_not_called()
    assert mock_trace.call_args.kwargs["status"] == "error"


def test_llm_call_failure_emits_error_event_without_raising():
    """Gemini raises: error event with the exception type only, trace llm_call_failed."""
    from app.workflow.steps.generate import generate_executor

    class ServerError(Exception):
        pass

    with (
        patch("app.workflow.steps.generate.resolve_template", return_value=("Plan a trip to {destination}.", 3)),
        patch("app.workflow.steps.generate._call_llm", side_effect=ServerError("500 secret upstream detail")),
        patch("app.workflow.steps.generate.write_trace") as mock_trace,
        patch.dict("os.environ", _ENV),
    ):
        event = json.loads(generate_executor(_make_step_input(cag_data=_CAG)).content)

    assert event["status"] == "error"
    assert event["error"] == "LLM call failed: ServerError"
    assert "secret upstream detail" not in json.dumps(event)
    trace = mock_trace.call_args.kwargs
    assert trace["status"] == "error"
    assert trace["error_type"] == "llm_call_failed"
    assert trace["prompt_template_key"] == "itinerary_with_context"
    assert trace["prompt_template_version"] == 3


# ---------------------------------------------------------------------------
# Daily budget ceiling (design decision 13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("budget", "amount", "expected"),
    [
        ("budget", None, 70.0),         # level default
        ("moderate", None, 200.0),      # level default
        ("moderate", 120, 120.0),       # amount overrides the level
        ("luxury", None, None),         # luxury without an amount: no ceiling
        ("luxury", 1500, 1500.0),       # luxury with an amount
        ("budget", 500, 500.0),         # amount above the level default is kept
    ],
)
def test_daily_budget_ceiling(budget, amount, expected):
    from app.workflow.budget import daily_budget_ceiling

    assert daily_budget_ceiling(budget, amount) == expected


def test_ceiling_text():
    from app.workflow.budget import ceiling_text

    assert ceiling_text(200.0) == "200 AUD per person per day, excluding accommodation"
    assert ceiling_text(None) == "none set"


def _resolved_prompt(additional_data: dict, template: str = "Ceiling: {daily_budget_ceiling}") -> str:
    """Run generate with a one-placeholder template (the ceiling by default); return the prompt."""
    from app.workflow.steps.generate import generate_executor

    captured = {}

    def fake_llm(prompt, api_key, model):
        captured["prompt"] = prompt
        return LLMResult('{"ok": true}')

    with (
        patch("app.workflow.steps.generate.resolve_template", return_value=(template, 3)),
        patch("app.workflow.steps.generate._call_llm", side_effect=fake_llm),
        patch("app.workflow.steps.generate.write_trace"),
        patch.dict("os.environ", _ENV),
    ):
        generate_executor(_make_step_input(cag_data=_CAG, additional_data=additional_data))
    return captured["prompt"]


def test_ceiling_from_the_level_in_prompt():
    assert _resolved_prompt({"budget": "moderate"}) == (
        "Ceiling: 200 AUD per person per day, excluding accommodation"
    )


def test_no_ceiling_in_prompt():
    assert _resolved_prompt({"budget": "luxury"}) == "Ceiling: none set"


def test_notes_substituted():
    """Spec scenario "Notes substituted"."""
    assert _resolved_prompt({"notes": "kids love animals"}, "Notes: {notes}") == "Notes: kids love animals"


@pytest.mark.parametrize("additional_data", [{}, {"notes": None}])
def test_no_notes(additional_data):
    """Spec scenario "No notes": {notes} becomes an empty string."""
    assert _resolved_prompt(additional_data, "Notes: [{notes}]") == "Notes: []"


def test_user_amount_in_prompt():
    assert _resolved_prompt({"budget": "luxury", "max_daily_budget_aud": 1500}) == (
        "Ceiling: 1500 AUD per person per day, excluding accommodation"
    )


# ---------------------------------------------------------------------------
# Structured output (design decision 4)
# ---------------------------------------------------------------------------


def test_generate_requests_json_with_itinerary_schema():
    """Spec scenario "Structured output requested"."""
    from app.workflow.output_validator import ItineraryOutput
    from app.workflow.steps.generate import _call_llm

    with (
        patch("app.workflow.steps.generate.genai.Client") as mock_client,
        patch("app.workflow.steps.generate.result_from_response", return_value=LLMResult("{}")),
    ):
        _call_llm(prompt="p", api_key="k", model="m")

    config = mock_client.return_value.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is ItineraryOutput
