## 1. Investigation

- [x] 1.1 Write a small experiment script to confirm which events Agno 2.5.14's streaming run (`stream=True` or the async interface) exposes, and whether Condition sub-steps also produce "step completed" events; Verify: record the conclusion under decision 2 in design.md and choose the approach

## 2. Routing decision becomes a plain Step

- [x] 2.1 Add a `retrieval_decision` Step that emits the decision event; change the Condition's evaluator to only read that event; remove `print()`; Verify: the updated `test_retrieval_decision.py` passes, and `capsys` asserts that stdout is empty
- [x] 2.2 Remove `redirect_stdout` and the stdout parsing logic from `main.py`; Verify: `grep redirect_stdout src` returns nothing

## 3. Incremental delivery

- [x] 3.1 Implement incremental delivery with the approach chosen in 1.1, with the workflow not running on the event-loop thread; Verify: a new test mocks a generate that takes 2 seconds and asserts the intake event is received within 2 seconds
- [x] 3.2 New test: a concurrent request to `/health` while generate is running returns 200 immediately
- [x] 3.3 New test: for two concurrent requests, each stream contains only the events of its own `session_id`

## 4. Regression and verification

- [x] 4.1 `dev.py test-all` passes completely; within it, the golden end-to-end test in `pytest -m integration` still asserts that all 6 steps appear — ran unit (535 passed) and integration (21 passed); the destructive tier was skipped by decision because this change touches no migrations
- [x] 4.2 Manual verification: run the Low-confidence preset in the browser and watch the panels appear one by one; record a screen capture or screenshots and compare with v0.1.0's "all appear at once" — checked by the user on 2026-11-01: early panels appeared quickly one by one, then a visible pause at generate; no screenshot kept (recorded in `docs/experiments.md`)
- [x] 4.3 Update the "How it works" diagram for POST /generate in the README
- [x] 4.4 Update the "Failure behaviour" diagrams in `docs/api.md`: `retrieval_decision` becomes a Step, and any failure that ends the stream early (e.g. the client disconnecting) is added; Verify: code review
