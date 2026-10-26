"""Behaviour classification and the behaviour correctness rate.

Each request's observed behaviour is one of:

- ``plan``          — a validated itinerary (the validate_output event completed)
- ``refuse``        — a 422 response carrying a guard reason code
- ``invalid_input`` — a 422 response without a reason code (field validation failed)
- ``error``         — an error event, an unhandled exception, an aborted stream,
                      or any other response

Public API::

    from evaluation.behaviour import behaviour_correctness, classify_response, observe

    outcome = observe(lambda: send_request(entry))   # never raises
    rates = behaviour_correctness([(entry, outcome), ...])
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Callable, Literal

from evaluation.dataset import DatasetEntry

Behaviour = Literal["plan", "refuse", "invalid_input", "error"]


@dataclass(frozen=True)
class Outcome:
    behaviour: Behaviour
    status_code: int | None = None
    reason: str | None = None
    events: list[dict] = field(default_factory=list)
    error: str | None = None
    # End-to-end wall-clock time of the request, set by observe().
    latency_ms: float | None = None

    @property
    def itinerary(self) -> dict | None:
        final = _event(self.events, "validate_output")
        return (final or {}).get("data", {}).get("itinerary")

    @property
    def degraded_mode(self) -> bool | None:
        """True when validate_output needed its corrective retry; None when it did not run."""
        final = _event(self.events, "validate_output")
        return None if final is None else final.get("data", {}).get("degraded_mode")


def parse_sse_events(body: str) -> list[dict]:
    """Decode the JSON payload of every ``data:`` line in an SSE body."""
    events = []
    for line in body.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def guard_reason(body: str) -> str | None:
    """Return the guard reason code of a 422 body, or None for plain field validation errors.

    Guard rejections are ``{"reason": <code>, "detail": <message>}``
    (harden-workflow-guardrails); FastAPI's own validation errors are
    ``{"detail": [...]}`` and carry no reason.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return reason if isinstance(reason, str) and reason else None


def classify_response(status_code: int, body: str) -> Outcome:
    """Classify one ``POST /generate`` response."""
    if status_code == 422:
        reason = guard_reason(body)
        return Outcome("refuse" if reason else "invalid_input", status_code, reason=reason)
    if status_code != 200:
        return Outcome("error", status_code, error=f"HTTP {status_code}")

    try:
        events = parse_sse_events(body)
    except json.JSONDecodeError as exc:
        return Outcome("error", status_code, error=f"malformed SSE event: {exc.msg}")

    failed = next((e for e in events if e.get("status") == "error"), None)
    if failed is not None:
        return Outcome("error", status_code, events=events,
                       error=f"{failed.get('step')}: {failed.get('error')}")
    final = _event(events, "validate_output")
    if final is None or "itinerary" not in final.get("data", {}):
        return Outcome("error", status_code, events=events, error="stream ended without an itinerary")
    return Outcome("plan", status_code, events=events)


def observe(send: Callable[[], tuple[int, str]]) -> Outcome:
    """Send one request, time it and classify it; an exception becomes an ``error`` outcome."""
    start = time.perf_counter()
    try:
        status_code, body = send()
    except Exception as exc:  # noqa: BLE001 — one entry must never stop the run
        outcome = Outcome("error", error=describe_exception(exc))
    else:
        outcome = classify_response(status_code, body)
    return replace(outcome, latency_ms=(time.perf_counter() - start) * 1000)


def describe_exception(exc: BaseException) -> str:
    """Name the root cause(s) of *exc*, unwrapping exception groups and ``__cause__`` chains.

    The app streams through an anyio task group, so a failure inside the workflow
    reaches the caller wrapped in an ``ExceptionGroup`` whose message says nothing.
    """
    leaves = []

    def walk(e: BaseException) -> None:
        if isinstance(e, BaseExceptionGroup):
            for sub in e.exceptions:
                walk(sub)
        elif e.__cause__ is not None:
            walk(e.__cause__)
        else:
            leaves.append(f"{type(e).__module__}.{type(e).__name__}: {e}")

    walk(exc)
    return "; ".join(leaves)[:1000]


def is_correct(expected: str, observed: Behaviour) -> bool:
    """Whether an observed behaviour matches the expected one.

    No observed class corresponds to a clarifying question yet, so ``clarify``
    entries always count as incorrect.
    """
    if expected == "clarify":
        return False
    return expected == observed


def behaviour_correctness(results: list[tuple[DatasetEntry, Outcome]]) -> dict:
    """Share of entries whose behaviour matches ``expected_behavior``, overall and per tag."""
    by_tag: dict[str, list[bool]] = defaultdict(list)
    by_expected: dict[str, list[bool]] = defaultdict(list)
    overall: list[bool] = []
    for entry, outcome in results:
        correct = is_correct(entry.expected_behavior, outcome.behaviour)
        overall.append(correct)
        by_expected[entry.expected_behavior].append(correct)
        for tag in entry.tags or ["untagged"]:
            by_tag[tag].append(correct)
    return {
        "overall": _rate(overall),
        "entries": len(overall),
        "by_expected_behavior": {key: _rate(v) for key, v in sorted(by_expected.items())},
        "by_tag": {key: _rate(v) for key, v in sorted(by_tag.items())},
    }


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _event(events: list[dict], step: str) -> dict | None:
    return next((e for e in events if e.get("step") == step), None)
