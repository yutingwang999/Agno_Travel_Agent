## 1. Investigation

- [ ] 1.1 Write a small experiment script to confirm which events Agno 2.5.14's streaming run (`stream=True` or the async interface) exposes, and whether Condition sub-steps also produce "step completed" events; Verify: record the conclusion under decision 2 in design.md and choose the approach

## 2. Routing decision becomes a plain Step

- [ ] 2.1 Add a `retrieval_decision` Step that emits the decision event; change the Condition's evaluator to only read that event; remove `print()`; Verify: the updated `test_retrieval_decision.py` passes, and `capsys` asserts that stdout is empty
- [ ] 2.2 Remove `redirect_stdout` and the stdout parsing logic from `main.py`; Verify: `grep redirect_stdout src` returns nothing

## 3. Incremental delivery

- [ ] 3.1 Implement incremental delivery with the approach chosen in 1.1, with the workflow not running on the event-loop thread; Verify: a new test mocks a generate that takes 2 seconds and asserts the intake event is received within 2 seconds
- [ ] 3.2 New test: a concurrent request to `/health` while generate is running returns 200 immediately
- [ ] 3.3 New test: for two concurrent requests, each stream contains only the events of its own `session_id`

## 4. Regression and verification

- [ ] 4.1 `dev.py test-all` passes completely; within it, the golden end-to-end test in `pytest -m integration` still asserts that all 6 steps appear
- [ ] 4.2 Manual verification: run the Low-confidence preset in the browser and watch the panels appear one by one; record a screen capture or screenshots and compare with v0.1.0's "all appear at once"
- [ ] 4.3 Update the "How it works" diagram for POST /generate in the README
- [ ] 4.4 Update the "Failure behaviour" diagrams in `docs/api.md`: `retrieval_decision` becomes a Step, and any failure that ends the stream early (e.g. the client disconnecting) is added; Verify: code review
