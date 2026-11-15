# Tasks

## 1. Planning

- [ ] 1.1 Update `docs/roadmap.md`: split item 3 into `parse-requests` and `clarify-requests` (the decisions on clarifying questions recorded with the second), add both to the near-term order table, and record dropping the category presets (template B, `cag_match` latency) as a later experiment; Verify: the roadmap names both changes in order and the experiment
- [ ] 1.2 Confirm the success criteria of design decision 8 with the user before any comparison run, and record the confirmed values in design.md; Verify: design decision 8 says "confirmed" with the date

## 2. Parser

- [ ] 2.1 Request object and parser schema (Pydantic): the form's fields, `preferences`, `is_travel_request` for the model's output, and the `/parse` response (`parse_id`, `request`, `preferences`, `assumptions`, `missing`); Verify: unit tests for the schemas
- [ ] 2.2 Seed the `request_parser` template v1 in `scripts/seed.py` (`TEMPLATE_DEFINITIONS`, `ACTIVE_TEMPLATE_VERSIONS`): read the sentence into the fields, leave unstated fields empty, take only a per-person daily amount, keep only leftover details in `notes`, say whether it is a travel request; Verify: `test_template_versions.py` covers the new key and its placeholders
- [ ] 2.3 Parser module: one structured-output call to `gemini-3.1-flash-lite` with the active template; code applies the defaults (`budget` → `moderate`, `travel_style` → the general default) and writes `assumptions`, leaves `destination` / `trip_length` empty and lists them in `missing` when unstated or outside 1–14; Verify: unit tests with a fake LLM for a complete sentence, no destination, unstated budget, stated budget, daily amount, trip too long, notes kept apart

## 3. Parse endpoint

- [ ] 3.1 `POST /parse` in `src/app/main.py`: body validation (`text` non-blank, at most 1000 characters), injection check on the text before the LLM call (`input_rejected`), `not_a_travel_request`, place-list lookup of the parsed destination (canonical name or `destination_out_of_scope`), 503 with a fixed message when the call fails or no template is active; Verify: unit tests for each scenario of the `request-parsing` spec, with the LLM faked
- [ ] 3.2 Add `not_a_travel_request` and its fixed message to the guard rejection body; Verify: unit tests for the body and message (`travel-workflow` scenarios)
- [ ] 3.3 Trace row `parse_request` under the returned `parse_id`, with latency, template key and version, token usage and `error_type`; never raises; Verify: unit test that the row is written, and that a trace failure does not fail the request
- [ ] 3.4 Integration test against the test database and Gemini: a complete sentence, a sentence without a destination, and a non-travel sentence through `/parse`; Verify: `python scripts/dev.py test-integration` passes
- [ ] 3.5 Document `/parse`, its response, rejections and failure in `docs/api.md`, and the parse endpoint in `CLAUDE.md`'s architecture section; Verify: code review

## 4. Frontend

- [ ] 4.1 Two ways in on `src/app/static/index.html`: a "Describe your trip" tab with a text box that calls `/parse`, fills the form, shows each assumption next to its field, highlights `missing` fields and shows a rejection message; generation only from the form; Verify: manual browser check (ask the user first): a complete sentence fills the form; "Five days somewhere warm with a beach" leaves the destination highlighted; a cover-letter request shows the rejection

## 5. Evaluation harness

- [ ] 5.1 Free-text path in the runner for `request_parser: true`: send `utterance` to `/parse`, then the parsed request to `/generate` with the configured template version; observed behaviour `refuse` for a parse rejection and `clarify` for a parse with `missing`; judges receive the entry's `form` fields on both paths; Verify: runner unit tests with faked services for each outcome
- [ ] 5.2 Parser metrics: slot extraction accuracy per slot as specified (null gold budget, preference recall), parsed field agreement with the `form`, parse latency p50 / p95 and parse cost, the parse cost added to the per-request cost; Verify: unit tests for each metric, including the spec scenarios
- [ ] 5.3 Parse-only mode in `scripts/eval_run.py` (`--parse-only`), and comparison table rows for the parser metrics in `eval_compare.py`; Verify: unit tests; a parse-only run on a few entries writes the parser metrics
- [ ] 5.4 Configs for the free-text path (the final `rebuild-rag` configuration with `request_parser: true`); `docs/evaluation.md` describes the free-text path, the new metrics and the `clarify` observation; Verify: config loads; code review of the docs

## 6. Measurement

- [ ] 6.1 Parse-only runs on the full dataset to check and, if needed, revise the parser prompt (a new template version each time); estimate the cost first and ask; Verify: the `docs/experiments.md` entry shows slot accuracy, field agreement, parse behaviour, latency and cost per prompt version
- [ ] 6.2 Compare the free-text path with the form path on the same entries (two runs each, same commit, criteria from task 1.2 fixed before the runs); estimate the cost first and ask; Verify: the `docs/experiments.md` entry shows both paths, the behaviour change for `clarify` entries, and whether each criterion is met

## 7. Regression

- [ ] 7.1 `python scripts/dev.py test-all` passes; the gate passes; `openspec validate parse-requests --strict` passes; Verify: command output

## Workflow follow-up

- Archive `parse-requests` (sync its specs), merge the branch by PR.
- Then plan `clarify-requests` from the decisions recorded in the roadmap.
