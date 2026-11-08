"""true-sse-streaming: events reach the client as each step finishes.

Starlette's TestClient (and httpx's ASGITransport) buffer the whole response,
so they cannot see when an event arrives.  These tests run the app in a real
uvicorn server on a background thread and read the stream over HTTP.

The workflow itself is real; only external services are patched, as in
test_workflow_skeleton.py.  The generate step blocks on a ``threading.Event``
the test controls, which makes "before generate finishes" deterministic
instead of depending on a sleep.

No DB or API key required.
"""

import json
import queue
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from app.main import app
from app.workflow.llm_usage import LLMResult

_VALID_ITINERARY_JSON = (
    '{"destination": "Sydney", "trip_length_days": 1, "budget_level": "moderate",'
    ' "travel_style": "family", "daily_itinerary": [{"day": 1, "morning": "Bondi Beach",'
    ' "afternoon": "Lunch", "evening": "Dinner", "estimated_cost_aud": 150.0}],'
    ' "total_estimated_cost_aud": 150.0, "key_tips": ["Book ahead"]}'
)

VALID_BODY = {
    "destination": "Sydney",
    "trip_length": 1,
    "budget": "moderate",
    "travel_style": "family",
}

# Generous upper bound for anything that should be immediate; the tests only
# wait this long when they are about to fail.
_TIMEOUT_S = 10


@pytest.fixture(autouse=True)
def reset_sse_app_status():
    """sse-starlette binds a module-level Event to the first loop it sees."""
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None


@pytest.fixture()
def generate_gate(monkeypatch):
    """Patch external services; the LLM call in generate blocks until ``release()``.

    ``finished`` is set once that call has returned.
    """
    from app.workflow.cag_matcher import MatchResult

    gate = threading.Event()
    finished = threading.Event()

    def _slow_llm(prompt, api_key, model):
        gate.wait(_TIMEOUT_S)
        finished.set()
        return LLMResult(_VALID_ITINERARY_JSON)

    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    # Every request retrieves (rebuild-rag); the knowledge base returns nothing here.
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.retrieve_documents", lambda **kwargs: []
    )
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.destination_in_knowledge_base", lambda destination, db_url: False
    )
    monkeypatch.setattr(
        "app.workflow.steps.cag_match.match_category",
        lambda **kwargs: MatchResult(
            category_key="family",
            confidence_score=0.95,
            tone="friendly",
            constraints="",
            is_fallback=False,
        ),
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan a trip to {destination}.", 1),
    )
    monkeypatch.setattr("app.workflow.steps.generate._call_llm", _slow_llm)
    yield SimpleNamespace(release=gate.set, finished=finished)
    gate.set()  # never leave a worker thread blocked after a failed test


@pytest.fixture()
def base_url():
    """Serve the app with uvicorn on a free port for the duration of a test."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _TIMEOUT_S
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(_TIMEOUT_S)


class _StreamReader:
    """Read one POST /generate stream on a thread, exposing events as they arrive."""

    def __init__(self, url: str, disconnect_after: str | None = None):
        self.events: queue.Queue = queue.Queue()
        self._url = url
        self._disconnect_after = disconnect_after
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        with httpx.stream("POST", self._url, json=VALID_BODY, timeout=_TIMEOUT_S) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[len("data: "):])
                    self.events.put(event)
                    if event["step"] == self._disconnect_after:
                        break  # leaving the block closes the connection
        self.events.put(None)  # end of stream

    def next_event(self) -> dict | None:
        return self.events.get(timeout=_TIMEOUT_S)

    def wait_for(self, step: str) -> list[dict]:
        """Return every event up to and including the one for ``step``."""
        received = []
        while True:
            event = self.next_event()
            assert event is not None, f"stream ended before {step!r}: {received}"
            received.append(event)
            if event["step"] == step:
                return received

    def read_to_end(self) -> list[dict]:
        received = []
        while (event := self.next_event()) is not None:
            received.append(event)
        return received


def test_first_events_arrive_before_generate_finishes(base_url, generate_gate):
    """Spec scenario "First event arrives before generation finishes"."""
    stream = _StreamReader(f"{base_url}/generate")

    early = stream.wait_for("rag_retrieve")
    assert [e["step"] for e in early] == ["intake", "cag_match", "retrieval_decision", "rag_retrieve"]
    assert not generate_gate.finished.is_set()

    generate_gate.release()
    rest = stream.read_to_end()
    assert [e["step"] for e in rest] == ["generate", "validate_output"]


def test_health_answers_while_generate_runs(base_url, generate_gate):
    """Spec scenario "Health check during generation"."""
    stream = _StreamReader(f"{base_url}/generate")
    stream.wait_for("rag_retrieve")

    response = httpx.get(f"{base_url}/health", timeout=2)

    assert response.status_code == 200
    assert not generate_gate.finished.is_set()
    generate_gate.release()
    stream.read_to_end()


def test_concurrent_requests_keep_their_own_events(base_url, generate_gate):
    """Spec scenario "Concurrent requests keep their own events"."""
    streams = [_StreamReader(f"{base_url}/generate") for _ in range(2)]
    # Both workflows are inside generate at the same time before either finishes.
    received = [s.wait_for("rag_retrieve") for s in streams]
    generate_gate.release()
    for events, stream in zip(received, streams):
        events.extend(stream.read_to_end())

    session_ids = [events[0]["session_id"] for events in received]
    assert session_ids[0] != session_ids[1]
    for events, session_id in zip(received, session_ids):
        assert len(events) == 6
        assert {e["session_id"] for e in events} == {session_id}


def test_client_disconnect_stops_the_workflow_at_the_next_step(
    base_url, generate_gate, monkeypatch
):
    """A disconnect during generate: generate finishes, validate_output never starts."""
    finished_steps: list[str] = []
    monkeypatch.setattr(
        "app.workflow.steps.generate.write_trace",
        lambda **kwargs: finished_steps.append(kwargs["step_name"]),
    )
    monkeypatch.setattr(
        "app.workflow.steps.validate_output.write_trace",
        lambda **kwargs: finished_steps.append(kwargs["step_name"]),
    )

    stream = _StreamReader(f"{base_url}/generate", disconnect_after="rag_retrieve")
    assert stream.read_to_end()[-1]["step"] == "rag_retrieve"
    time.sleep(0.5)  # let the server notice the closed connection while generate runs
    generate_gate.release()

    deadline = time.monotonic() + _TIMEOUT_S
    while "generate" not in finished_steps:
        assert time.monotonic() < deadline, "generate never finished"
        time.sleep(0.01)
    time.sleep(0.5)  # time validate_output would need if it were started

    assert finished_steps == ["generate"]
