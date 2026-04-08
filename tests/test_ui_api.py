"""Unit tests for GET /traces/{session_id} (feat/ui checklist).

Verifies:
  - Returns 200 + correct JSON array when rows exist (DB mocked)
  - Returns 404 when no rows found for the session_id
  - Every object in the response includes session_id, step_name, status,
    latency_ms, and created_at
  - The generate step object includes prompt_template_key and
    prompt_template_version

No live DB or Docker required — get_traces is patched at the SQLAlchemy
Session level so the endpoint logic is tested in isolation.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SESSION_ID = "test-session-abc123"

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# Representative rows returned by the mocked DB query
_MOCK_ROWS = [
    MagicMock(
        session_id=SESSION_ID,
        step_name="intake",
        status="completed",
        latency_ms=42.5,
        prompt_template_key=None,
        prompt_template_version=None,
        degraded_mode=None,
        error_type=None,
        created_at=_NOW,
    ),
    MagicMock(
        session_id=SESSION_ID,
        step_name="cag_match",
        status="completed",
        latency_ms=310.2,
        prompt_template_key=None,
        prompt_template_version=None,
        degraded_mode=None,
        error_type=None,
        created_at=_NOW,
    ),
    MagicMock(
        session_id=SESSION_ID,
        step_name="retrieval_decision",
        status="completed",
        latency_ms=5.1,
        prompt_template_key=None,
        prompt_template_version=None,
        degraded_mode=None,
        error_type=None,
        created_at=_NOW,
    ),
    MagicMock(
        session_id=SESSION_ID,
        step_name="generate",
        status="completed",
        latency_ms=1254.8,
        prompt_template_key="high_confidence_minimal_context",
        prompt_template_version=1,
        degraded_mode=None,
        error_type=None,
        created_at=_NOW,
    ),
    MagicMock(
        session_id=SESSION_ID,
        step_name="validate_output",
        status="completed",
        latency_ms=18.3,
        prompt_template_key=None,
        prompt_template_version=None,
        degraded_mode=False,
        error_type=None,
        created_at=_NOW,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_rows(rows):
    """Return a context manager that patches the DB Session to return *rows*."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rows

    mock_execute_result = MagicMock()
    mock_execute_result.scalars.return_value = mock_scalars

    mock_session_instance = MagicMock()
    mock_session_instance.execute.return_value = mock_execute_result
    mock_session_instance.__enter__ = MagicMock(return_value=mock_session_instance)
    mock_session_instance.__exit__ = MagicMock(return_value=False)

    mock_session_cls = MagicMock(return_value=mock_session_instance)
    return patch("app.main.Session", mock_session_cls)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Checklist: returns 200 + JSON array when rows exist
# ---------------------------------------------------------------------------


def test_get_traces_returns_200_when_rows_exist(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    assert response.status_code == 200


def test_get_traces_returns_json_array_when_rows_exist(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == len(_MOCK_ROWS)


# ---------------------------------------------------------------------------
# Checklist: returns 404 when no rows found
# ---------------------------------------------------------------------------


def test_get_traces_returns_404_when_no_rows(client):
    with _mock_db_rows([]):
        response = client.get("/traces/nonexistent-session")
    assert response.status_code == 404


def test_get_traces_404_response_has_detail(client):
    with _mock_db_rows([]):
        response = client.get("/traces/nonexistent-session")
    body = response.json()
    assert "detail" in body


# ---------------------------------------------------------------------------
# Checklist: every object includes required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"session_id", "step_name", "status", "latency_ms", "created_at"}


def test_get_traces_every_row_has_required_fields(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        missing = REQUIRED_FIELDS - row.keys()
        assert not missing, (
            f"Row for step '{row.get('step_name')}' is missing fields: {missing}"
        )


def test_get_traces_session_id_matches_in_all_rows(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        assert row["session_id"] == SESSION_ID


def test_get_traces_step_name_is_non_empty_string(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        assert isinstance(row["step_name"], str) and row["step_name"]


def test_get_traces_status_is_non_empty_string(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        assert isinstance(row["status"], str) and row["status"]


def test_get_traces_latency_ms_is_numeric(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        assert isinstance(row["latency_ms"], (int, float))


def test_get_traces_created_at_is_present(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        assert row["created_at"] is not None


# ---------------------------------------------------------------------------
# Checklist: generate row includes prompt_template_key and
#            prompt_template_version
# ---------------------------------------------------------------------------


def test_get_traces_generate_row_has_prompt_template_key(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    generate_row = next((r for r in rows if r["step_name"] == "generate"), None)
    assert generate_row is not None, "No 'generate' row in response"
    assert "prompt_template_key" in generate_row
    assert generate_row["prompt_template_key"] == "high_confidence_minimal_context"


def test_get_traces_generate_row_has_prompt_template_version(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    generate_row = next((r for r in rows if r["step_name"] == "generate"), None)
    assert generate_row is not None, "No 'generate' row in response"
    assert "prompt_template_version" in generate_row
    assert generate_row["prompt_template_version"] == 1


def test_get_traces_non_generate_rows_have_null_template_fields(client):
    with _mock_db_rows(_MOCK_ROWS):
        response = client.get(f"/traces/{SESSION_ID}")
    rows = response.json()
    for row in rows:
        if row["step_name"] != "generate":
            assert row.get("prompt_template_key") is None
            assert row.get("prompt_template_version") is None
