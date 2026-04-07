"""Trace logger — writes a single row to ``trace_events`` after each workflow step.

Usage::

    from app.workflow.trace_logger import write_trace

    write_trace(
        db_url=os.environ["DATABASE_URL"],
        session_id=session_id,
        step_name="generate",
        status="completed",
        latency_ms=342.7,
        prompt_template_key="high_confidence_minimal_context",
        prompt_template_version=1,
    )

All DB errors are caught and logged — a trace write failure must never crash
the workflow step that called it.
"""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.trace_event import TraceEvent

logger = logging.getLogger(__name__)


def write_trace(
    db_url: str,
    session_id: str,
    step_name: str,
    status: str,
    latency_ms: float,
    prompt_template_key: str | None = None,
    prompt_template_version: int | None = None,
    degraded_mode: bool | None = None,
    error_type: str | None = None,
) -> None:
    """Insert one row into ``trace_events`` for the completed step.

    Args:
        db_url:                  SQLAlchemy database URL.
        session_id:              Unique identifier for the workflow run.
        step_name:               Name of the completed step (e.g. ``"generate"``).
        status:                  Step outcome — ``"completed"`` or ``"error"``.
        latency_ms:              Wall-clock duration of the step in milliseconds.
        prompt_template_key:     ``generate`` step only — the template key used.
        prompt_template_version: ``generate`` step only — the active version number.
        degraded_mode:           ``validate_output`` step only — True when a retry
                                 was attempted.
        error_type:              ``validate_output`` step only — short description
                                 of the failure when the step ended in error.
    """
    try:
        engine = create_engine(db_url)
        with Session(engine) as session:
            trace_event = TraceEvent(
                session_id=session_id,
                step_name=step_name,
                status=status,
                latency_ms=latency_ms,
                prompt_template_key=prompt_template_key,
                prompt_template_version=prompt_template_version,
                degraded_mode=degraded_mode,
                error_type=error_type,
            )
            session.add(trace_event)
            session.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "trace_logger: failed to write trace event "
            "(session_id=%r, step_name=%r) — continuing without trace",
            session_id,
            step_name,
        )
