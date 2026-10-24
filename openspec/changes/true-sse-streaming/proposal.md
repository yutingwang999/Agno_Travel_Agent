# Proposal

## Why

`POST /generate` is nominally SSE, but in reality it runs the whole workflow synchronously inside an `async` generator, collects all the events and then pushes them in one go: the user has to wait until the LLM finishes generating before seeing the result of the first step; the synchronous call blocks the event loop, so the server cannot handle other requests in the meantime; the `retrieval_decision` event is obtained by capturing `print()` with `redirect_stdout`, and `redirect_stdout` changes `sys.stdout` for the whole process, so concurrent requests interfere with each other.

## What Changes

- Each step's SSE event is pushed as soon as the step completes; event order stays the same.
- The workflow does not run synchronously on the event-loop thread; the server can still respond to other requests while it runs.
- Remove `redirect_stdout` and `print()`: the routing-decision event goes through the same delivery channel as the other steps' events.
- The frontend already reads the response as a stream, so no change is expected there — it only needs verification.

## Capabilities

### New Capabilities

(None)

### Modified Capabilities

- `travel-workflow`: remove the old "Event delivery timing", replaced by the new "Incremental event delivery"; add "request handling does not block".
- `intent-routing`: modify "Routing decision event" (remove the description of stdout).

## Impact

- `src/app/main.py` (`_run_workflow`, `generate`, the `_STEP_ORDER` sorting logic)
- `src/app/workflow/steps/retrieval_decision.py`, `travel_workflow.py`
- `tests/test_fastapi_service.py`, `tests/test_retrieval_decision.py`, `tests/test_golden.py` (the end-to-end part)
- The API response format is unchanged; only the arrival time of events changes, so this is not a breaking change.
- **Dependencies**: independent of the RAG-related changes; the routing events of `add-cag-mode` assume the state after this change is complete.
