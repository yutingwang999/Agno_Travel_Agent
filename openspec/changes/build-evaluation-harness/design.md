# Design

## Context

- The v0.1.0 input is a structured form (4 fields); the system has no step that "parses a request from free text"; out-of-scope and contradictory requests are not handled at all and get an itinerary as usual.
- The knowledge base is 13 handwritten documents; the documents have no `source` / `section` metadata, only a title.
- Traces record only latency and template version; Gemini responses carry usage metadata (input / output token counts), but the code does not read it.
- Evaluation calls a paid API and depends on a database that tests do not wipe (see `isolate-test-database`).

## Goals / Non-Goals

**Goals:**
- One evaluation dataset and one set of metrics that can cover every later change on the roadmap (RAG, guardrails, request parsing, multi-turn) without being redesigned each time.
- Reproducible results: every report records the dataset version, corpus version, configuration and models.

**Non-Goals:**
- Do not integrate GitHub Actions in this change (roadmap item 8).
- Do not build multi-turn evaluation cases in this change (add them once the multi-turn revision feature is designed; see the roadmap).
- Do not improve any functionality — the baseline is meant to measure v0.1.0 as it is, including what it cannot do.

## Decisions

1. **Every evaluation entry contains both `form` and `utterance`.**
   `form` holds the structured form fields that drive the current system; `utterance` is a free-text phrasing of the same request (possibly mixed Chinese–English), used together with `gold_slots` to evaluate request parsing in the future (roadmap item 3). v0.1.0 has no parser, so slot accuracy is marked N/A.
   Alternative: store free text only — then the current system could not run the evaluation.

2. **An `expected_behavior` field: `plan` / `refuse` / `clarify`.**
   Out-of-scope requests are labelled `refuse`; contradictory requests or requests missing key information are labelled `clarify`. The metrics report a separate "behaviour correctness rate". v0.1.0 generates an itinerary for every request, so the `refuse` and `clarify` classes will be 0 in the baseline — which is exactly what the baseline should show.

3. **End-to-end evaluation calls `POST /generate` in-process through FastAPI's `TestClient`**, so input validation (and, later, the input guardrails) is within the scope of evaluation; retrieval metrics instead call the retrieval component directly for every entry, unaffected by routing (otherwise high-confidence requests would never retrieve and Recall could not be computed).

4. **Relevance is labelled by `(source, section)`.** v0.1.0's handwritten documents have neither field, so by convention `source="handwritten"` and `section=<document title>`. When the corpus changes (e.g. `rebuild-rag`), `relevant_sections` must be re-labelled for the new corpus and the dataset's corpus version bumped; reports always record which version was used.

5. **Constraint satisfaction is decided jointly by code and the judge model.**
   - Correct number of days, within budget: checked by code. The budget caps live in `app/workflow/config.py` (per-budget-level daily cost cap × number of days); the runtime rules in `harden-workflow-guardrails` reuse them.
   - Attractions in the destination: v0.1.0 has no geocoding, so the judge model decides (once roadmap item 4 integrates Nominatim this can become a code check).

6. **Faithfulness is judged entry by entry by the judge model**: whether each specific claim in the itinerary is supported by the knowledge context given to the model for that request. The judge model is configured separately from the generation model. 20 entries are sampled at random and scored manually against the same criteria, and the agreement rate is reported.

7. **Cost is computed as token count × price table.** The price table lives in `eval/pricing.yaml`, is maintained by hand, and its date is stated in reports; prices are not hardcoded.

8. **Result file layout**: `eval/runs/<time>-<config name>/` stores each entry's raw result (JSONL) and a summary (JSON); `eval_compare.py` reads several summaries and produces a Markdown table.

9. **A dedicated evaluation database, with knowledge-base tables named by corpus version.**
   Evaluation uses `travel_agent_eval_db`, pointed to by `EVAL_DATABASE_URL`, separate from both the development and test databases: evaluation writes a large number of trace rows, which should not pollute the development database, and tests wipe the test database. The table name in `knowledge_base.build_knowledge` becomes configurable (still `travel_docs` by default, so the development environment is unchanged); tables in the evaluation database are named by corpus version (`travel_docs_v1`, later `travel_docs_v2_c500`, etc.), and the run configuration specifies which one to use. This way the v0.1.0 baseline can still be re-run after `rebuild-rag`, and several chunking configurations can be kept side by side for comparison.
   Alternative: rebuild the same table every time the corpus changes — old results could not be reproduced or compared side by side.

10. **Costs are always interpreted as "per person, in AUD".** The v0.1.0 template says "for a traveller" without making this explicit, which is especially ambiguous for the family style. The baseline interprets costs per person and says so in the report; `harden-workflow-guardrails` will write "per person" into the generation templates. The caps in `config.py` are "per person per day" caps.

11. **Faithfulness counts only four kinds of specific claims**: opening hours, prices, specific venue or attraction names, and transport modes and durations. General descriptions such as "enjoy the harbour views" are not claims. Faithfulness is reported separately for requests "with knowledge context" and "without knowledge context", because v0.1.0's high-confidence path has no context at all and mixing the two would hide the change brought by retrieval.

12. **Behaviour falls into four classes**: `plan`, `refuse` (a 422 with a guardrail reason code), `invalid_input` (a 422 without a reason code, i.e. field validation failed), `error` (an error event, an unhandled exception, an interrupted stream). In v0.1.0 a failed LLM call raises straight through, so the harness must record it as `error` for that entry and continue evaluating the rest.

13. **Retrieval metrics first run intake and intent matching, then build the query exactly the way the workflow does**, because the query includes `matched_category`. This way what is evaluated is the query the workflow actually sends.

14. **Cost has three parts**: generation calls (from the token counts in the trace), embedding calls (estimated from call count and input length using the price table), and judge calls. The first two count towards "cost per request"; the judge cost is reported separately, because it is the cost of evaluation, not of the product.

15. **Gate thresholds may change, but a record must be left.** Intentional behaviour changes (e.g. starting to refuse out-of-scope requests) will lower some metrics. In that case, update the thresholds in the same change and write in `docs/experiments.md` which change did it and why.

## Risks / Trade-offs

- [The evaluation dataset is self-written and may be biased towards our own approach] → Write and commit the dataset before any experiment; any later modification is recorded in `docs/experiments.md` with what changed and why.
- [The judge model is itself biased] → Calibrate with manual scores and report the agreement rate; if the agreement rate is too low, improve the judge prompt first, then use the judge results.
- [A full evaluation is expensive and easily hits Gemini's rate limits] → Very low default concurrency, with retries and backoff; day to day, run only the smoke subset.
- [LLM output is non-deterministic, so two runs of the same configuration fluctuate] → Leave a margin in the smoke-subset gate thresholds; for formal comparisons run each configuration 2 times and report the mean.

## Migration Plan

- New Alembic migration 0005: add nullable `input_tokens` and `output_tokens` columns to `trace_events`. Rollback: downgrade drops the two columns without affecting existing data.
- Create the evaluation database `travel_agent_eval_db`: migrate → seed categories and templates → write v0.1.0's 13 documents into `travel_docs_v1`. The development and test databases are unaffected.
