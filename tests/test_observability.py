"""feat/observability merge checklist tests.

Verifies:
  - write_trace is importable and callable without error
  - write_trace DB failure is swallowed — never crashes the caller
  - every step executor calls write_trace exactly once per invocation
  - intake, cag_match, retrieval_decision, rag_retrieve pass the correct
    common fields (session_id, step_name, status, latency_ms)
  - generate passes prompt_template_key and prompt_template_version in addition
  - validate_output passes degraded_mode=False on clean success
  - validate_output passes degraded_mode=True + error_type on retry-succeeded
  - validate_output passes degraded_mode=True + error_type on both-failed
  - latency_ms is a positive float in every trace call
  - integration: after a full workflow run, trace_events has exactly 6 rows
    for that session_id with all required non-null fields

No DB or Docker required for unit tests — write_trace is patched.
Integration tests are marked with @pytest.mark.integration and require a
live PostgreSQL instance + GEMINI_API_KEY.
"""

import json
import os
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

VALID_ITINERARY = {
    "destination": "Sydney",
    "trip_length_days": 1,
    "budget_level": "moderate",
    "travel_style": "family",
    "daily_itinerary": [
        {
            "day": 1,
            "morning": "Bondi Beach",
            "afternoon": "Lunch",
            "evening": "Dinner",
            "estimated_cost_aud": 150.0,
        }
    ],
    "total_estimated_cost_aud": 450.0,
    "key_tips": ["Book ahead"],
}
VALID_ITINERARY_JSON = json.dumps(VALID_ITINERARY)


def _make_sse_content(step: str, data: dict, session_id: str = "test-session") -> str:
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


def _make_basic_step_input(session_id: str = "test-session"):
    """StepInput with all intake fields — used by intake, cag_match, retrieval_decision."""
    from agno.workflow.types import StepInput

    return StepInput(
        input="plan a trip",
        additional_data={
            "session_id": session_id,
            "destination": "sydney",
            "trip_length": 5,
            "budget": "moderate",
            "travel_style": "family",
        },
    )


def _make_generate_step_input(
    confidence_score: float = 0.85,
    session_id: str = "test-session",
):
    """StepInput with cag_match output — used by generate_executor."""
    from agno.workflow.types import StepInput, StepOutput

    cag_output = StepOutput(
        step_name="cag_match",
        content=_make_sse_content(
            "cag_match",
            {
                "matched_category": "family",
                "confidence_score": confidence_score,
                "tone": "friendly",
                "constraints": "child-friendly",
                "is_fallback": False,
            },
            session_id,
        ),
    )
    return StepInput(
        input="plan a trip",
        additional_data={
            "session_id": session_id,
            "destination": "sydney",
            "trip_length": 5,
            "budget": "moderate",
            "travel_style": "family",
        },
        previous_step_outputs={"cag_match": cag_output},
    )


def _make_validate_step_input(
    raw_llm_output: str = VALID_ITINERARY_JSON,
    session_id: str = "test-session",
):
    """StepInput carrying generate step output — used by validate_output_executor."""
    from agno.workflow.types import StepInput, StepOutput

    generate_output = StepOutput(
        step_name="generate",
        content=_make_sse_content(
            "generate",
            {
                "raw_llm_output": raw_llm_output,
                "prompt_template_key": "high_confidence_minimal_context",
                "prompt_template_version": 1,
            },
            session_id,
        ),
    )
    return StepInput(
        additional_data={"session_id": session_id},
        previous_step_outputs={"generate": generate_output},
    )


# ---------------------------------------------------------------------------
# trace_logger module
# ---------------------------------------------------------------------------


def test_trace_logger_importable():
    from app.workflow.trace_logger import write_trace  # noqa: F401


def test_write_trace_db_failure_is_swallowed(monkeypatch):
    """A DB error inside write_trace must never propagate to the caller."""
    from app.workflow.trace_logger import write_trace

    monkeypatch.setattr(
        "app.workflow.trace_logger.create_engine",
        lambda url: (_ for _ in ()).throw(RuntimeError("DB unavailable")),
    )

    # Must not raise
    write_trace(
        db_url="postgresql://x:x@localhost/x",
        session_id="sid",
        step_name="intake",
        status="completed",
        latency_ms=10.0,
    )


def test_write_trace_session_commit_called(monkeypatch):
    """write_trace must commit the session after adding the row."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session_cls = MagicMock(return_value=mock_session)

    monkeypatch.setattr("app.workflow.trace_logger.create_engine", MagicMock())
    monkeypatch.setattr("app.workflow.trace_logger.Session", mock_session_cls)

    from app.workflow.trace_logger import write_trace

    write_trace(
        db_url="postgresql://x:x@localhost/x",
        session_id="sid",
        step_name="intake",
        status="completed",
        latency_ms=5.0,
    )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


def test_write_trace_row_fields_match_args(monkeypatch):
    """The TraceEvent row passed to session.add must carry all supplied args."""
    from app.models.trace_event import TraceEvent

    added_rows = []
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.add.side_effect = added_rows.append
    mock_session_cls = MagicMock(return_value=mock_session)

    monkeypatch.setattr("app.workflow.trace_logger.create_engine", MagicMock())
    monkeypatch.setattr("app.workflow.trace_logger.Session", mock_session_cls)

    from app.workflow.trace_logger import write_trace

    write_trace(
        db_url="postgresql://x:x@localhost/x",
        session_id="sid-123",
        step_name="generate",
        status="completed",
        latency_ms=123.4,
        prompt_template_key="high_confidence_minimal_context",
        prompt_template_version=1,
        degraded_mode=False,
        error_type=None,
    )

    assert len(added_rows) == 1
    row = added_rows[0]
    assert isinstance(row, TraceEvent)
    assert row.session_id == "sid-123"
    assert row.step_name == "generate"
    assert row.status == "completed"
    assert row.latency_ms == 123.4
    assert row.prompt_template_key == "high_confidence_minimal_context"
    assert row.prompt_template_version == 1
    assert row.degraded_mode is False
    assert row.error_type is None


# ---------------------------------------------------------------------------
# intake_executor — write_trace call
# ---------------------------------------------------------------------------


def test_intake_calls_write_trace_once(monkeypatch):
    """intake_executor must call write_trace exactly once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.intake.write_trace", mock_write)

    from app.workflow.steps.intake import intake_executor

    intake_executor(_make_basic_step_input())
    mock_write.assert_called_once()


def test_intake_trace_fields(monkeypatch):
    """intake trace call must supply session_id, step_name='intake', status, latency_ms."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.intake.write_trace", mock_write)

    from app.workflow.steps.intake import intake_executor

    intake_executor(_make_basic_step_input(session_id="sid-intake"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-intake"
    assert kwargs["step_name"] == "intake"
    assert kwargs["status"] == "completed"
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# cag_match_executor — write_trace call
# ---------------------------------------------------------------------------


def test_cag_match_calls_write_trace_once(monkeypatch):
    """cag_match_executor must call write_trace exactly once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.cag_match.write_trace", mock_write)

    from app.workflow.cag_matcher import MatchResult
    monkeypatch.setattr(
        "app.workflow.steps.cag_match.match_category",
        lambda **kwargs: MatchResult(
            category_key="family",
            confidence_score=0.85,
            tone="friendly",
            constraints="child-friendly",
            is_fallback=False,
        ),
    )

    from app.workflow.steps.cag_match import cag_match_executor

    cag_match_executor(_make_basic_step_input())
    mock_write.assert_called_once()


def test_cag_match_trace_fields(monkeypatch):
    """cag_match trace call must supply session_id, step_name='cag_match', status, latency_ms."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.cag_match.write_trace", mock_write)

    from app.workflow.cag_matcher import MatchResult
    monkeypatch.setattr(
        "app.workflow.steps.cag_match.match_category",
        lambda **kwargs: MatchResult(
            category_key="family",
            confidence_score=0.85,
            tone="friendly",
            constraints="child-friendly",
            is_fallback=False,
        ),
    )

    from app.workflow.steps.cag_match import cag_match_executor

    cag_match_executor(_make_basic_step_input(session_id="sid-cag"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-cag"
    assert kwargs["step_name"] == "cag_match"
    assert kwargs["status"] == "completed"
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# retrieval_decision_evaluator — write_trace call
# ---------------------------------------------------------------------------


def test_retrieval_decision_calls_write_trace_once(monkeypatch, capsys):
    """retrieval_decision_evaluator must call write_trace exactly once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.retrieval_decision.write_trace", mock_write
    )

    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_basic_step_input())
    mock_write.assert_called_once()


def test_retrieval_decision_trace_fields(monkeypatch, capsys):
    """retrieval_decision trace must carry session_id, step_name, status, latency_ms."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.retrieval_decision.write_trace", mock_write
    )

    from app.workflow.steps.retrieval_decision import retrieval_decision_evaluator

    retrieval_decision_evaluator(_make_basic_step_input(session_id="sid-rd"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-rd"
    assert kwargs["step_name"] == "retrieval_decision"
    assert kwargs["status"] == "completed"
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# rag_retrieve_executor — write_trace call
# ---------------------------------------------------------------------------


def test_rag_retrieve_calls_write_trace_once(monkeypatch):
    """rag_retrieve_executor must call write_trace exactly once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.rag_retrieve.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.retrieve_documents",
        lambda **kwargs: [],
    )

    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    rag_retrieve_executor(_make_basic_step_input())
    mock_write.assert_called_once()


def test_rag_retrieve_trace_fields(monkeypatch):
    """rag_retrieve trace must carry session_id, step_name='rag_retrieve', status, latency_ms."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.rag_retrieve.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.retrieve_documents",
        lambda **kwargs: [],
    )

    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    rag_retrieve_executor(_make_basic_step_input(session_id="sid-rag"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-rag"
    assert kwargs["step_name"] == "rag_retrieve"
    assert kwargs["status"] == "completed"
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


def test_rag_retrieve_trace_called_even_on_retrieval_failure(monkeypatch):
    """write_trace must still be called when retrieve_documents raises."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.rag_retrieve.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.retrieve_documents",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("pgvector error")),
    )

    from app.workflow.steps.rag_retrieve import rag_retrieve_executor

    rag_retrieve_executor(_make_basic_step_input())
    mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# generate_executor — write_trace call (includes template key + version)
# ---------------------------------------------------------------------------


def test_generate_calls_write_trace_once(monkeypatch):
    """generate_executor must call write_trace exactly once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.generate.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.generate import generate_executor

    generate_executor(_make_generate_step_input())
    mock_write.assert_called_once()


def test_generate_trace_includes_prompt_template_key(monkeypatch):
    """generate trace must include the prompt_template_key used."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.generate.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.generate import generate_executor

    generate_executor(_make_generate_step_input(confidence_score=0.85))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["prompt_template_key"] == "high_confidence_minimal_context"


def test_generate_trace_includes_prompt_template_version(monkeypatch):
    """generate trace must include the prompt_template_version resolved from DB."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.generate.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 7),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.generate import generate_executor

    generate_executor(_make_generate_step_input())

    kwargs = mock_write.call_args.kwargs
    assert kwargs["prompt_template_version"] == 7


def test_generate_trace_common_fields(monkeypatch):
    """generate trace must carry session_id, step_name='generate', status, latency_ms."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.generate.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.generate import generate_executor

    generate_executor(_make_generate_step_input(session_id="sid-gen"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-gen"
    assert kwargs["step_name"] == "generate"
    assert kwargs["status"] == "completed"
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


def test_generate_trace_low_confidence_uses_low_confidence_key(monkeypatch):
    """Low confidence_score must produce low_confidence_with_retrieval template key in trace."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    mock_write = MagicMock()
    monkeypatch.setattr("app.workflow.steps.generate.write_trace", mock_write)
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.generate import generate_executor

    generate_executor(_make_generate_step_input(confidence_score=0.50))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["prompt_template_key"] == "low_confidence_with_retrieval"


# ---------------------------------------------------------------------------
# validate_output_executor — write_trace call (degraded_mode + error_type)
# ---------------------------------------------------------------------------


def _patch_validate_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@localhost/x")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def test_validate_output_calls_write_trace_once_on_success(monkeypatch):
    """validate_output must call write_trace exactly once when first parse succeeds."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )

    from app.workflow.steps.validate_output import validate_output_executor

    validate_output_executor(_make_validate_step_input())
    mock_write.assert_called_once()


def test_validate_output_trace_degraded_mode_false_on_success(monkeypatch):
    """Clean validation pass: trace must record degraded_mode=False."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )

    from app.workflow.steps.validate_output import validate_output_executor

    validate_output_executor(_make_validate_step_input(session_id="sid-val-ok"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["session_id"] == "sid-val-ok"
    assert kwargs["step_name"] == "validate_output"
    assert kwargs["status"] == "completed"
    assert kwargs["degraded_mode"] is False
    assert isinstance(kwargs["latency_ms"], float)
    assert kwargs["latency_ms"] >= 0


def test_validate_output_trace_degraded_mode_true_on_retry_success(monkeypatch):
    """Retry-succeeded: trace must record degraded_mode=True and an error_type."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.resolve_template",
        lambda template_key, db_url, version=None: (
            "Fix this: {validation_errors}\n{raw_llm_output}", 1
        ),
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output._call_llm",
        lambda prompt, api_key, model: VALID_ITINERARY_JSON,
    )

    from app.workflow.steps.validate_output import validate_output_executor

    # Empty string → first parse fails → retry with patched LLM → succeeds
    validate_output_executor(_make_validate_step_input(raw_llm_output="not json"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["step_name"] == "validate_output"
    assert kwargs["status"] == "completed"
    assert kwargs["degraded_mode"] is True
    assert kwargs["error_type"] is not None


def test_validate_output_trace_degraded_mode_true_on_both_failed(monkeypatch):
    """Both-failed: trace must record status='error', degraded_mode=True, error_type."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.resolve_template",
        lambda template_key, db_url, version=None: (
            "Fix this: {validation_errors}\n{raw_llm_output}", 1
        ),
    )
    # Retry also returns invalid JSON
    monkeypatch.setattr(
        "app.workflow.steps.validate_output._call_llm",
        lambda prompt, api_key, model: "still not json",
    )

    from app.workflow.steps.validate_output import validate_output_executor

    validate_output_executor(_make_validate_step_input(raw_llm_output="not json"))

    kwargs = mock_write.call_args.kwargs
    assert kwargs["step_name"] == "validate_output"
    assert kwargs["status"] == "error"
    assert kwargs["degraded_mode"] is True
    assert kwargs["error_type"] is not None


def test_validate_output_trace_called_once_on_both_failed(monkeypatch):
    """write_trace must be called exactly once even when both validation attempts fail."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.resolve_template",
        lambda template_key, db_url, version=None: (
            "Fix this: {validation_errors}\n{raw_llm_output}", 1
        ),
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output._call_llm",
        lambda prompt, api_key, model: "still not json",
    )

    from app.workflow.steps.validate_output import validate_output_executor

    validate_output_executor(_make_validate_step_input(raw_llm_output="not json"))
    mock_write.assert_called_once()


def test_validate_output_trace_called_once_on_correction_template_missing(monkeypatch):
    """write_trace must be called once when the correction template is not found."""
    _patch_validate_env(monkeypatch)
    mock_write = MagicMock()
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace", mock_write
    )

    from app.workflow.template_resolver import TemplateNotFoundError
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.resolve_template",
        lambda template_key, db_url, version=None: (_ for _ in ()).throw(
            TemplateNotFoundError("not found")
        ),
    )

    from app.workflow.steps.validate_output import validate_output_executor

    validate_output_executor(_make_validate_step_input(raw_llm_output="not json"))

    mock_write.assert_called_once()
    kwargs = mock_write.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["degraded_mode"] is True
    assert kwargs["error_type"] == "correction_template_unavailable"


# ---------------------------------------------------------------------------
# Integration tests — require live PostgreSQL + GEMINI_API_KEY
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_integration_six_trace_rows_after_full_workflow_run(monkeypatch):
    """After a full low-confidence workflow run, trace_events must have 6 rows
    for that session_id — one per step."""
    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.trace_event import TraceEvent
    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    db_url = os.environ["DATABASE_URL"]
    session_id = f"integration-obs-{uuid.uuid4()}"

    low_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.50,
        tone="friendly",
        constraints="child-friendly",
        is_fallback=False,
    )

    import contextlib
    import io

    with patch(
        "app.workflow.steps.cag_match.match_category",
        return_value=low_confidence_result,
    ):
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            travel_workflow.run(
                input="plan a trip to Sydney",
                additional_data={
                    "session_id": session_id,
                    "destination": "sydney",
                    "trip_length": 3,
                    "budget": "moderate",
                    "travel_style": "family",
                },
            )

    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.scalars(
            select(TraceEvent).where(TraceEvent.session_id == session_id)
        ).all()

    assert len(rows) == 6, (
        f"Expected 6 trace rows, got {len(rows)}: {[r.step_name for r in rows]}"
    )


@pytest.mark.integration
def test_integration_all_trace_rows_have_required_fields(monkeypatch):
    """Every trace row must have non-null session_id, step_name, status, latency_ms."""
    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.trace_event import TraceEvent
    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    db_url = os.environ["DATABASE_URL"]
    session_id = f"integration-fields-{uuid.uuid4()}"

    low_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.50,
        tone="friendly",
        constraints="child-friendly",
        is_fallback=False,
    )

    import contextlib
    import io

    with patch(
        "app.workflow.steps.cag_match.match_category",
        return_value=low_confidence_result,
    ):
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            travel_workflow.run(
                input="plan a trip to Melbourne",
                additional_data={
                    "session_id": session_id,
                    "destination": "melbourne",
                    "trip_length": 3,
                    "budget": "moderate",
                    "travel_style": "family",
                },
            )

    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.scalars(
            select(TraceEvent).where(TraceEvent.session_id == session_id)
        ).all()

    for row in rows:
        assert row.session_id, f"session_id is null/empty on step '{row.step_name}'"
        assert row.step_name, "step_name is null/empty"
        assert row.status, f"status is null/empty on step '{row.step_name}'"
        assert row.latency_ms is not None, (
            f"latency_ms is null on step '{row.step_name}'"
        )


@pytest.mark.integration
def test_integration_generate_row_has_template_fields(monkeypatch):
    """The generate trace row must have non-null prompt_template_key and version."""
    import uuid

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.trace_event import TraceEvent
    from app.workflow.cag_matcher import MatchResult
    from app.workflow.travel_workflow import travel_workflow

    db_url = os.environ["DATABASE_URL"]
    session_id = f"integration-gen-{uuid.uuid4()}"

    high_confidence_result = MatchResult(
        category_key="family",
        confidence_score=0.90,
        tone="friendly",
        constraints="child-friendly",
        is_fallback=False,
    )

    import contextlib
    import io

    with patch(
        "app.workflow.steps.cag_match.match_category",
        return_value=high_confidence_result,
    ):
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            travel_workflow.run(
                input="plan a trip to Brisbane",
                additional_data={
                    "session_id": session_id,
                    "destination": "brisbane",
                    "trip_length": 3,
                    "budget": "moderate",
                    "travel_style": "family",
                },
            )

    engine = create_engine(db_url)
    with Session(engine) as session:
        generate_row = session.scalar(
            select(TraceEvent).where(
                TraceEvent.session_id == session_id,
                TraceEvent.step_name == "generate",
            )
        )

    assert generate_row is not None, "No trace row found for generate step"
    assert generate_row.prompt_template_key is not None, (
        "prompt_template_key is null on generate row"
    )
    assert generate_row.prompt_template_version is not None, (
        "prompt_template_version is null on generate row"
    )
