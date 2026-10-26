## 1. Error handling

- [ ] 1.1 Catch exceptions from `match_category` in `cag_match_executor`, return the empty-data fallback result, and write `error_type="embedding_failed"` to the trace; Verify: a new unit test mocks the embedding call to raise and asserts the event has `status="completed"` and `is_fallback=true`
- [ ] 1.2 When the template fallback succeeds, update `template_key` so the event and trace record the template actually used; Verify: a unit test mocks the high-confidence template as missing and asserts both the event and the trace show `low_confidence_with_retrieval`
- [ ] 1.3 Catch exceptions from `_call_llm` in generate, emit a `"LLM call failed: <type>"` error event, and write `error_type="llm_call_failed"` to the trace; Verify: a unit test mocks the LLM to raise and asserts no exception escapes
- [ ] 1.4 When the generate event is an error, validate_output emits `"Generation failed upstream"` directly; catch exceptions from the correction call and write `error_type="correction_call_failed"` to the trace; Verify: unit tests assert no exception escapes in either case, and in the first case `_call_llm` is not called
- [ ] 1.5 Fix the docstring of `steps/cag_match.py` (in-memory cosine computation, not a pgvector query) and the comments in `steps/rag_retrieve.py` that mention `source_documents`; Verify: code review
- [ ] 1.6 Construct `travel_workflow` with `telemetry=False`; add a commented-out `AGNO_TELEMETRY=false` to `.env.example` explaining that it overrides the code for all Agno instances; Verify: a unit test asserts `travel_workflow.telemetry is False`; with the app running and `AGNO_TELEMETRY` unset, a `POST /generate` makes no request to `os-api.agno.com`

## 2. Template versions and cost unit

- [ ] 2.1 Add an Alembic migration: first set every active row except the highest version of each key inactive, then create the partial unique index `UNIQUE (template_key) WHERE is_active`; add this migration to the migration-chain check in `test_db_schema.py` and add a read-only "partial unique index exists" check (`integration`); Verify: `upgrade head` / `downgrade -1` both succeed on the test database; inserting a second active row makes the database raise an error; `dev.py test-destructive` passes
- [ ] 2.2 Change seed to "insert missing versions; the highest version of each key is active, the others inactive"; Verify: on a database that already has v1, add a v2 definition and run seed; v2 becomes active and v1 inactive
- [ ] 2.3 Add a new version of each of the three templates stating "all costs are AUD per person, excluding accommodation"; Verify: after seeding, query all active templates; every text contains "AUD per person, excluding accommodation"

## 3. Structured output

- [ ] 3.1 Experiment: call Gemini with a `response_schema` generated from the current `ItineraryOutput` and confirm what is supported; Verify: record the conclusion under decision 4 in design.md
- [ ] 3.2 Both generate and the correction call request JSON + schema; keep the code-fence stripping logic as a fallback; Verify: unit tests assert the request parameters include the schema

## 4. Business rules

- [ ] 4.1 Restructure validation as "schema validation + rule list", each rule a pure function, with failure messages carrying the rule name and values; Verify: the existing `test_validate_output.py` passes completely
- [ ] 4.2 The day-count rule compares against the user's requested `trip_length`; Verify: unit tests cover "5 days requested, output consistently 3 days"
- [ ] 4.3 Cost consistency rule; Verify: unit tests cover Totals disagree and Rounding tolerated
- [ ] 4.4 Budget cap rule (computed per person, reusing the per-person daily caps in `config.py`); Verify: unit tests cover exceeding the cap and luxury having no cap
- [ ] 4.5 Unsupported specifics rule (opening-hours statements, currency amounts; comparison text taken from `chunk_text` in the `rag_retrieve` event); Verify: unit tests cover the three scenarios Invented opening hours / Schedule time / Price taken from the context, plus several ways of writing amounts

## 5. Input guardrails

- [ ] 5.1 Prepare `data/places/australia.tsv` (name → canonical English name; states, capitals, major towns and tourist destinations, from openly licensed place-name data; Chinese names of the major cities added by hand) and document its source and licence; Verify: the file contains every Australian destination in the knowledge base and the evaluation dataset, including the Chinese names used by `chinese_destination` entries
- [ ] 5.2 Implement the destination guardrail: on a match replace with the canonical name, otherwise return 422 + `destination_out_of_scope`, without calling any external API; Verify: API tests cover Foreign city / Australian city / Chinese city name, and when a request is rejected the mocked LLM and embedding are not called
- [ ] 5.3 Implement the injection guardrail (pattern list in configuration, English and Chinese patterns), 422 + `input_rejected`; Verify: API tests cover the scenarios, including a Chinese injection and ordinary Chinese text that must pass
- [ ] 5.4 Both guards reject through one exception class and FastAPI exception handler that returns `{"reason": <code>, "detail": <fixed message>}`; the message is fixed per code and never echoes input, the matched pattern or field, or any internal detail; Verify: API tests assert the exact body for each code, that a submitted injection string does not appear in the response, and that a field validation 422 has no `reason`
- [ ] 5.5 Frontend: on a field validation 422, show each error's `msg` instead of `[object Object]` (render with `textContent`); guard rejections show `detail`; Verify: manually submit `trip_length` = 0 and an out-of-scope destination and check both banners
- [ ] 5.6 The README and `docs/api.md` explain the two 422 reason codes and the rejection body, the supported Chinese place names, and that the place-name table may wrongly reject small places

## 6. Testing and regression

- [ ] 6.1 Change the destination of the low-confidence case in `test_golden.py` from `"abcdefg hi"` to a valid Australian place name, still with a rare travel_style; Verify: actually run it with `pytest -m integration tests/test_golden.py`, confirm `confidence_score < 0.85`, and the test passes
- [ ] 6.2 Confirm the evaluation dataset has enough `prompt_injection` entries (add more if not, and record the dataset modification in `docs/experiments.md`)
- [ ] 6.3 Run a full evaluation with the evaluation harness, compare against the v0.1.0 baseline, and write it into `docs/experiments.md`; update gate thresholds as needed and record the reason; Verify: the success criteria in the proposal are met
- [ ] 6.4 `dev.py test-all` passes completely (unit, integration including golden, destructive); `openspec validate harden-workflow-guardrails --strict` passes
