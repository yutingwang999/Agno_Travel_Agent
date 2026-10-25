# Design

## Context

- The v0.1.0 input is a structured form (4 fields); the system has no step that "parses a request from free text"; out-of-scope and contradictory requests are not handled at all and get an itinerary as usual.
- The form has no travel dates and no party size, only the trip length.
- The knowledge base is 13 handwritten documents; the documents have no `source` / `section` metadata, only a title.
- Traces record only latency and template version; Gemini responses carry usage metadata (input / output token counts), but the code does not read it.
- The generation model defaults to `gemini-2.0-flash` in code (`steps/generate.py`) and can be overridden with the `LLM_MODEL` environment variable.
- Each day of the itinerary has a single `estimated_cost_aud`; the template does not say what it covers (in particular whether accommodation is included).
- The knowledge-base table name is a constant in `knowledge_base.py`, and `steps/rag_retrieve.py` does not pass one, so retrieval always reads `ai.travel_docs`.
- Evaluation calls a paid API and depends on a database that tests do not wipe (see `isolate-test-database`).

## Goals / Non-Goals

**Goals:**
- One evaluation dataset and one set of metrics that can cover every later change on the roadmap (RAG, guardrails, request parsing, multi-turn) without being redesigned each time.
- Reproducible results: every report records the dataset version, corpus version, configuration and models.

**Non-Goals:**
- Do not integrate GitHub Actions in this change (roadmap item 8).
- Do not build multi-turn evaluation cases in this change (add them once the multi-turn revision feature is designed; see the roadmap).
- Do not improve any functionality — the baseline is meant to measure v0.1.0 as it is, including what it cannot do.
- Do not add accommodation or live prices (hotels, meals). The form has no dates or party size, which live hotel prices require, and live prices would make two runs of the same configuration incomparable.

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
   - The caps are per person per day, in AUD, excluding accommodation: `budget` 70, `moderate` 200; `luxury` has no cap, so the budget constraint is reported N/A for `luxury` entries. They are derived from three meals a day plus local transport and tickets:

     | AUD per person per day | budget | moderate |
     | --- | --- | --- |
     | Breakfast / lunch / dinner | 10 / 15 / 20 | 20 / 30 / 50 |
     | Local transport | 15 | 25 |
     | Tickets and activities | 0–10 | 50 |
     | Total | ~70 | ~175 |
     | Cap (with margin) | 70 | 200 |

     Meal prices are a single national reference (cost-of-living sources give roughly AUD 15–30 for an inexpensive meal and AUD 40–60 per person for a mid-range dinner). The cap is a line for "clearly over budget", not an estimate of normal spend, hence the margin. `config.py` stores only the two caps and is commented with this breakdown, its sources and their date; the values are initial values and any change is recorded.
     Alternative: per-city meal tables — the available data is too inconsistent for the extra precision to mean anything. Live prices (e.g. a paid cost-of-living API) — rejected for the same reproducibility reason as hotels.
   - Attractions in the destination: v0.1.0 has no geocoding, so the judge model decides (once roadmap item 4 integrates Nominatim this can become a code check).

6. **Faithfulness is judged entry by entry by the judge model**: whether each specific claim in the itinerary is supported by the knowledge context given to the model for that request. 20 entries are sampled at random and scored manually against the same criteria, and the agreement rate is reported.
   The judge is OpenAI `gpt-6-luna`, called through the `openai` SDK with structured outputs; every response is validated with Pydantic. It comes from a different provider than the generation model, which reduces a judge's tendency to favour output from its own model family. If the agreement rate is too low, first improve the judge prompt, then try a stronger model from the same family and re-calibrate.
   Alternative: Agno's `AgentAsJudgeEval` — it forces the response into a single pass/fail or 1–10 score (overriding any custom output schema), so it cannot return per-claim judgements, and it sends telemetry by default. Agno's other evals target Agents, Teams or tool calls, which this workflow does not have.

7. **Cost is computed as token count × price table.** The price table lives in `eval/pricing.yaml`, is maintained by hand, and its date is stated in reports; prices are not hardcoded. It covers every model a run uses (generation, embedding and judge), with each price checked against the provider's official pricing page.

8. **Result file layout**: `eval/runs/<time>-<config name>/` stores each entry's raw result (JSONL) and a summary (JSON); `eval_compare.py` reads several summaries and produces a Markdown table.

9. **A dedicated evaluation database, with knowledge-base tables named by corpus version.**
   Evaluation uses `travel_agent_eval_db`, pointed to by `EVAL_DATABASE_URL`, separate from both the development and test databases: evaluation writes a large number of trace rows, which should not pollute the development database, and tests wipe the test database. The table name in `knowledge_base.build_knowledge` becomes configurable (still `travel_docs` by default, so the development environment is unchanged); tables in the evaluation database are named by corpus version (`travel_docs_v1`, later `travel_docs_v2_c500`, etc.), and the run configuration specifies which one to use. This way the v0.1.0 baseline can still be re-run after `rebuild-rag`, and several chunking configurations can be kept side by side for comparison.
   Alternative: rebuild the same table every time the corpus changes — old results could not be reproduced or compared side by side.

10. **Costs are always interpreted as "per person, in AUD, excluding accommodation".** The v0.1.0 template says "for a traveller" without making this explicit, which is especially ambiguous for the family style, and does not say whether a stay is included. The baseline interprets costs this way and says so in the report; `harden-workflow-guardrails` will write the same wording into the generation templates. The caps in `config.py` are "per person per day" caps.

11. **Faithfulness counts only four kinds of specific claims**: opening hours, prices, specific venue or attraction names, and transport modes and durations. General descriptions such as "enjoy the harbour views" are not claims. Faithfulness is reported separately for requests "with knowledge context" and "without knowledge context", because v0.1.0's high-confidence path has no context at all and mixing the two would hide the change brought by retrieval.

12. **Behaviour falls into four classes**: `plan`, `refuse` (a 422 with a guardrail reason code), `invalid_input` (a 422 without a reason code, i.e. field validation failed), `error` (an error event, an unhandled exception, an interrupted stream). In v0.1.0 a failed LLM call raises straight through, so the harness must record it as `error` for that entry and continue evaluating the rest.

13. **Retrieval metrics first run intake and intent matching, then build the query exactly the way the workflow does**, because the query includes `matched_category`. This way what is evaluated is the query the workflow actually sends.

14. **Cost has three parts**: generation calls (from the token counts in the trace), embedding calls (estimated from call count and input length using the price table), and judge calls. The first two count towards "cost per request"; the judge cost is reported separately, because it is the cost of evaluation, not of the product.

15. **Gate thresholds may change, but a record must be left.** Intentional behaviour changes (e.g. starting to refuse out-of-scope requests) will lower some metrics. In that case, update the thresholds in the same change and write in `docs/experiments.md` which change did it and why.

16. **Evaluation runs generate with `gemini-3.1-flash-lite`**, set through `LLM_MODEL` in the run configuration; the code default is not changed in this change. The baseline therefore measures "v0.1.0 logic with `gemini-3.1-flash-lite`", the model later changes will be compared on, so each later comparison changes one variable only. The run conditions table states the generation model.

17. **The knowledge-base table is selected with a `KNOWLEDGE_TABLE_NAME` environment variable**, read by `knowledge_base.py` and passed through by `steps/rag_retrieve.py`; unset, it is `travel_docs`. Because the evaluation calls the app in-process, an environment variable is the only way to choose the table without changing the API. This, plus token recording, is the only change to `steps/`, and both are measurement-only.

18. **`prompt_injection` entries are labelled `refuse`.** The correct behaviour on an injection is to refuse, which is what `harden-workflow-guardrails` implements (422 `input_rejected`). The baseline scores 0 on this tag and the guardrail change should raise it.
    Alternative: label them `plan` (ignore the injection and plan normally) — the guardrail's 422 would then count as wrong.

19. **`clarify` entries count as incorrect until a clarifying behaviour exists.** No observed class corresponds to `clarify`, because v0.1.0 never asks a question back. The change that introduces clarification (request parsing or multi-turn revision) defines how a clarification is observed and adds it as a behaviour class.

20. **`expected_facts` is optional.** No metric in this change uses it; it is reserved for a possible later fact-coverage metric, so labelling it is not required now.

21. **Smoke subset and gate.** The smoke subset is 10 entries: 2 that take the high-confidence path, 2 that take the low-confidence (retrieval) path, all three budget levels covered, and one each tagged `out_of_scope`, `prompt_injection`, `contradictory` and `mixed_language`. Gated metrics: format pass rate, trip-length constraint, budget constraint and Recall@5 (each a minimum), and error rate (a maximum). Faithfulness is not gated (judge noise and cost), nor is behaviour correctness (the baseline is 0 on `refuse` until the guardrails exist). Each threshold is the worse of the two baseline runs loosened by one entry, i.e. 10 percentage points, so normal LLM variation does not fail the gate.

22. **Evaluation runs send no Agno telemetry.** `eval_run.py` sets `AGNO_TELEMETRY=false` before importing the app, because each request would otherwise send a run event to `os-api.agno.com`; until `harden-workflow-guardrails`, only the tests set it.

23. **`mixed_language` entries behave like ordinary entries in the baseline.** v0.1.0 reads only `form`, whose `destination` is English for these entries, so the tag says nothing about mixed-language handling until a request parser reads `utterance`. The baseline report states this.

## Risks / Trade-offs

- [The evaluation dataset is self-written and may be biased towards our own approach] → Write and commit the dataset before any experiment; the user reviews every entry; any later modification is recorded in `docs/experiments.md` with what changed and why.
- [The judge model is itself biased] → Calibrate with manual scores and report the agreement rate; if the agreement rate is too low, improve the judge prompt first, then use the judge results.
- [A full evaluation is expensive and can hit rate limits] → The accounts are on paid tiers; default concurrency 4, with retries and backoff; day to day, run only the smoke subset.
- [LLM output is non-deterministic, so two runs of the same configuration fluctuate] → Leave a margin in the smoke-subset gate thresholds; for formal comparisons run each configuration 2 times and report the mean.
- [The budget caps rest on rough reference prices] → They only flag "clearly over budget"; the derivation is kept next to the values so they can be revisited, and changes are recorded.

## Migration Plan

- New Alembic migration 0005: add nullable `input_tokens` and `output_tokens` columns to `trace_events`. Rollback: downgrade drops the two columns without affecting existing data.
- Create the evaluation database `travel_agent_eval_db`: migrate → seed categories and templates → write v0.1.0's 13 documents into `travel_docs_v1`. The development and test databases are unaffected.
