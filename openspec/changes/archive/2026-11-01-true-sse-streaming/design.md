# Design

## Context

- `travel_workflow.run(...)` is a synchronous call; only after it returns are the `step_results` iterated to collect events (`main.py:84-151`).
- `retrieval_decision` is the evaluator of an Agno `Condition`; it can only return a `bool` and has no `StepOutput` to carry an event, which is why `print()` was used to write the event to stdout.
- The installed Agno version is 2.5.14.

## Goals / Non-Goals

**Goals:**
- Push each event as soon as its step completes; workflow execution does not block the event loop; no shared mutable global state between requests.

**Non-Goals:**
- No token-level LLM streaming (generate still returns the complete text at once).
- Do not change the event structure or the frontend.

## Decisions

1. **Split the routing decision into a plain Step; the Condition only reads its result.**
   A new `Step(name="retrieval_decision", ...)` emits the decision event (in `StepOutput.content`, like the other steps); the `Condition`'s evaluator only reads `routing_decision` from that event and no longer has side effects of its own. This removes the need for stdout.
   Alternative: have the evaluator write the event to a per-session queue — workable, but the evaluator still has side effects, and events would come from two kinds of source.

2. **Event delivery: prefer Agno's streaming run events; fall back to a thread + queue approach if per-step output content is not available.**
   - Preferred: `workflow.run(..., stream=True)` (or the corresponding async interface), listening for "step completed" events and pushing the step's content from them. Before implementing, write a small experiment to confirm which event types version 2.5.14 exposes and whether Condition sub-steps also produce events.
   - Alternative: run the workflow in a thread with `run_in_threadpool`; when each step's executor completes, it puts its event into an `asyncio.Queue` isolated by `session_id` (via `loop.call_soon_threadsafe`), and the SSE generator takes events from the queue.
   Both approaches satisfy the spec; the choice is an implementation detail.

   **Experiment result (task 1.1, Agno 2.5.14):** `workflow.run(..., stream=True, stream_events=True)` returns a synchronous iterator that yields each event as the step finishes (a 1 s step showed up 1 s later, not at the end). Every step, including one nested inside a `Condition`, yields a `StepCompletedEvent` whose `step_name` and `content` are the step's own `StepOutput`. `StepOutputEvent` is **not** yielded for steps nested in a `Condition`, so it cannot be used. A skipped branch yields only `ConditionExecutionStarted/CompletedEvent`, with no step events. **Chosen:** the preferred approach. `main.py` iterates the sync stream through Starlette's `iterate_in_threadpool` (each `next()` runs off the event loop) and forwards the `content` of every `StepCompletedEvent` that parses as an SSE event; all other event types are ignored. No queue and no shared state is needed. The `Condition` is renamed (`retrieval_branch`) because the new plain Step takes the name `retrieval_decision`; trace rows keep `step_name="retrieval_decision"`.

3. **No more sorting by `_STEP_ORDER`.** Events are sent in actual completion order; the workflow itself runs sequentially, so the order is naturally correct. No test needed `_STEP_ORDER`, so it was removed rather than kept.

## Risks / Trade-offs

- [Agno's streaming event interface changes between versions] → Confirm the interface with an experiment first; concentrate the adapter code in one function in `main.py`, covered by tests.
- [Client disconnects mid-run] → With the chosen approach the server pulls the workflow one step at a time, so a disconnect stops it at the next step boundary: the running step finishes (Starlette's worker-thread call cannot be interrupted), later steps never start, and the trace ends at that step. Decided with the user on 2026-11-01 in favour of this over running to completion: no Gemini spend after the client has gone. Documented in `docs/api.md` (Failure behaviour → Client disconnects) and covered by `tests/test_streaming.py`.
- [TestClient reads SSE differently from a browser and cannot detect "arriving step by step"] → In tests, mock a slow step and assert that the first event is received before the slow step finishes.

## Open Questions

- ~~Should a running workflow be cancelled after the client disconnects?~~ Resolved: it stops at the next step boundary (see Risks). Interrupting the step that is running (e.g. an in-flight Gemini call) is not attempted.
