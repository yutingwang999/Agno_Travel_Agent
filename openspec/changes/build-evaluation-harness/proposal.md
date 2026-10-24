# Proposal

## Why

v0.1.0 has no number that measures quality: we don't know whether retrieval is accurate, whether itineraries satisfy the constraints, or how much one request costs. Without evaluation, every later improvement (RAG rebuild, guardrail rules, multi-turn revision) can only be judged by feel, and we cannot write credible conclusions such as "Recall@5 went from X to Y". So the evaluation harness must be built before every other functional change, and a baseline must first be run on v0.1.0.

## What Changes

- **Evaluation dataset**: 50–100 labelled requests covering different destinations, budgets, trip lengths and styles, including contradictory requests, out-of-scope requests (e.g. foreign cities) and mixed Chinese–English requests. Each entry has both structured form fields and one free-text sentence, and is labelled with the expected behaviour (plan / refuse / clarify).
- **Metrics for four stages**:
  - Intent and request parsing: slot extraction accuracy (destination, trip length, budget, preferences)
  - Retrieval: Recall@k, MRR (relevance labelled by "source + section")
  - Generation: faithfulness (LLM judge, with 20 manually scored entries to calibrate the judge), constraint satisfaction rate (correct number of days, within budget, attractions in the destination)
  - System: format pass rate, retry rate, p50 / p95 latency, cost per request
- **Traces record LLM token usage**, as the data source for the cost metric.
- **Running and comparison**: one command runs a full evaluation for a configuration and writes result files; another command turns several runs into a comparison table that goes into `docs/experiments.md`.
- **Regression gate**: a smoke subset of about 10 entries and a metric threshold file; the command exits with a non-zero status when a metric falls below its threshold, for later CI integration (GitHub Actions integration is roadmap item 8).
- **Baseline**: run the first full evaluation on v0.1.0.

## Capabilities

### New Capabilities

- `evaluation-harness`: evaluation dataset format, metric definitions for each stage, run and comparison reports, regression gate.

### Modified Capabilities

- `travel-workflow`: traces add the token usage of LLM calls.

## Impact

- New `eval/` (dataset, threshold file, run results), `scripts/eval_run.py`, `scripts/eval_compare.py`, `docs/experiments.md`
- New Alembic migration: add `input_tokens` and `output_tokens` columns to `trace_events`
- `steps/generate.py`, `steps/validate_output.py`: read token counts from the usage metadata of the Gemini response and write them to the trace
- `app/workflow/config.py`: add a daily cost cap per budget level (shared by the constraint satisfaction rate and the later guardrail rules)
- **Paid API**: every full evaluation calls Gemini (generation + judge); day-to-day regression runs only the smoke subset
- **Dependencies**: after `isolate-test-database`, before every functional change. Every later change must cite this harness's metrics in its proposal's success criteria and report before/after comparisons

**Success criteria**

- `docs/experiments.md` contains a complete v0.1.0 baseline report with numbers for the metrics of all four stages (metrics that don't apply are explicitly marked N/A with a reason).
- The agreement rate between the judge model and manual scores has been measured and written into the report.
- The smoke-subset gate command passes reliably on v0.1.0 (thresholds set from the baseline).
