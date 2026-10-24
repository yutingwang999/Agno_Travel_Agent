## 1. Evaluation environment

- [ ] 1.1 Add `EVAL_DATABASE_URL` (pointing to `travel_agent_eval_db`) to `.env.example`; make the table name in `knowledge_base.build_knowledge` configurable, still `travel_docs` by default; Verify: without the new variable set, the development environment's behaviour and `count-rows` output are unchanged
- [ ] 1.2 Add `eval-db-setup` to `scripts/dev.py`: create the evaluation database → migrate → seed categories and templates → write v0.1.0's documents into `travel_docs_v1`; share the database-creation and migration logic with `test-db-setup`; Verify: two consecutive runs both succeed, and the row counts of the development and test databases are unchanged

## 2. Evaluation dataset (completed and committed before any experiment)

- [ ] 2.1 Define the dataset format; write loading and coverage-check scripts (required fields, labels, budget levels, `form.destination` of `mixed_language` entries must be English); Verify: unit tests use deliberately invalid samples and assert that the check fails
- [ ] 2.2 Write 50–100 entries: multiple destinations, all three budget levels, varied trip lengths and styles, plus the four classes `contradictory` / `out_of_scope` (including foreign cities) / `prompt_injection` / `mixed_language`; Verify: the coverage check passes
- [ ] 2.3 Label `relevant_sections` against v0.1.0's 13 documents (`source="handwritten"`, `section` is the title) and record the corpus version as v1; Verify: every `plan` entry has at least one relevant section, or is explicitly marked as needing no knowledge
- [ ] 2.4 Label `expected_facts` and `gold_slots`; Verify: the coverage check confirms these two fields are non-empty for `plan` entries

## 3. Token usage

- [ ] 3.1 Add Alembic migration 0005 adding `input_tokens` / `output_tokens` to `trace_events`; add 0005 to the migration-chain check in `test_db_schema.py` and the two columns to the `trace_events` column check; Verify: `upgrade head` and `downgrade -1` both succeed on the test database; `dev.py test-destructive` passes
- [ ] 3.2 generate and validate_output read token counts from the usage metadata of the Gemini response and write them to the trace; Verify: unit tests mock a response with usage and assert the values in the trace

## 4. Metrics

- [ ] 4.1 Add a "per person per day" cost cap for each budget level to `config.py`; Verify: code review (the values are labelled as initial values, with units)
- [ ] 4.2 Implement retrieval metrics: run intake and intent matching first, build the query the same way as the workflow, then call the retrieval component directly and compute Recall@k and MRR@k; Verify: unit tests with small hand-built examples assert the values; another test asserts that the query text matches the workflow's
- [ ] 4.3 Implement behaviour classification (`plan` / `refuse` / `invalid_input` / `error`; exceptions do not abort the evaluation) and the behaviour correctness rate; Verify: unit tests cover all four classes and "the remaining entries are still evaluated after one entry raises"
- [ ] 4.4 Implement the trip-length and budget constraints (interpreted per person), format pass rate, retry rate, error rate and latency; Verify: unit tests cover every metric
- [ ] 4.5 Implement cost computation: generation (tokens), embedding (call count and input length), judge (reported separately), with prices from the dated `eval/pricing.yaml`; Verify: unit tests assert the values with fixed prices
- [ ] 4.6 Implement the judge model: extract the four kinds of claims and judge faithfulness (reported separately for requests with and without context), and whether attractions are in the destination; the judge model is configured separately; Verify: run it end to end on 2 entries and manually check that the judge output is reasonable
- [ ] 4.7 Implement the record format for manual scores and the agreement-rate computation; Verify: unit tests

## 5. Running and reporting

- [ ] 5.1 Implement `scripts/eval_run.py` (calls in-process through TestClient, connects to the evaluation database, selects the knowledge-base table from the configuration, low concurrency, with retries and backoff, writes results to `eval/runs/<run id>/`); the summary records the dataset version, corpus version and knowledge-base table, configuration, models, template key and version, price-table date, git commit SHA and `git_dirty`; Verify: a `--subset smoke` run completes, the development database gets no new trace rows, and every condition field in the summary has a value
- [ ] 5.2 Implement `scripts/eval_compare.py`, producing a Markdown comparison table that marks runs with `git_dirty = true` with ⚠️; Verify: build a table from two smoke runs, one of them run with uncommitted changes, and the warning appears in the table
- [ ] 5.3 Implement the gate: `eval/thresholds.yaml`; exit with a non-zero status when below a threshold; create a "Threshold change log" section in `docs/experiments.md`; Verify: temporarily set one threshold to 1.0, and the command fails and names the metric

## 6. Baseline

- [ ] 6.1 On the commit where this change is fully implemented (no uncommitted changes in the working tree), run 2 full evaluations, fill in the "v0.1.0 baseline" table and the index in `docs/experiments.md`, and note "costs interpreted per person". Relative to tag `v0.1.0`, this commit only adds measurement code (token recording, configurable knowledge-base table name, evaluation scripts) and does not change system behaviour; Verify: all four stages have numbers, or N/A with a reason; `git_dirty` is false for both runs; `git diff v0.1.0 -- src/app/workflow/steps` contains only token-recording changes
- [ ] 6.2 Manually score 20 results and report the judge model's agreement rate; Verify: the number is written into `docs/experiments.md`
- [ ] 6.3 Set the thresholds in `thresholds.yaml` from the baseline (leaving a margin); Verify: the gate passes on v0.1.0 2 times in a row
- [ ] 6.4 Add a "How to run the evaluation" section to the README explaining the difference between the evaluation and test databases (evaluation numbers come only from the evaluation database); `dev.py test-all` passes; `openspec validate build-evaluation-harness --strict` passes
