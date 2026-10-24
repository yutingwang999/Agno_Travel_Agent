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

3. **No more sorting by `_STEP_ORDER`.** Events are sent in actual completion order; the workflow itself runs sequentially, so the order is naturally correct. `_STEP_ORDER` is kept only for test assertions.

## Risks / Trade-offs

- [Agno's streaming event interface changes between versions] → Confirm the interface with an experiment first; concentrate the adapter code in one function in `main.py`, covered by tests.
- [With the thread approach, the workflow keeps running in the background after the client disconnects, continuing to consume LLM calls] → This change accepts that and records it under Open Questions.
- [TestClient reads SSE differently from a browser and cannot detect "arriving step by step"] → In tests, mock a slow step and assert that the first event is received before the slow step finishes.

## Open Questions

- Should a running workflow be cancelled after the client disconnects? It does not affect this change's spec and can be handled later.
