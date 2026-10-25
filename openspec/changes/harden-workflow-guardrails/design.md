# Design

## Context

- Every step emits its event through `build_sse_event` and writes a trace with `write_trace`; trace writing already swallows exceptions.
- `cag_matcher.match_category`, `generate._call_llm` and `validate_output._call_llm` have no try/except, so exceptions pass through Agno all the way up to FastAPI and show up as an interrupted request.
- In the template fallback branch, `generate_executor` only updates `template_text` and `template_version`, not `template_key` (`generate.py:240-247`).
- `parse_llm_output` first strips markdown code fences, then runs `json.loads`, then Pydantic validation, and finally checks whether `len(daily_itinerary)` equals the `trip_length_days` in the output.
- The input has only Pydantic field validation; `travel_style` is free text and is spliced straight into the prompt.
- `build-evaluation-harness` has already defined the per-budget-level daily cost caps in `config.py`.
- Agno's `Workflow` defaults to `telemetry=True` and sends one event per run (workflow id, session id, run id, db type) to `os-api.agno.com`. The `AGNO_TELEMETRY` environment variable, when set, overrides the constructor value, and it is read again before every send. `tests/conftest.py` already sets `AGNO_TELEMETRY=false` for tests (`isolate-test-database`); the running app still sends it.

## Goals / Non-Goals

**Goals:**
- When an external dependency (Gemini, the database) fails, every step emits `status="error"` or an explicit degraded result instead of raising an unhandled exception.
- Every business rule that can be checked by code is checked by code, without relying on the LLM behaving.
- Obviously unreasonable input is stopped before it enters the workflow.

**Non-Goals:**
- No automatic retry and backoff on LLM call failure.
- No runtime check of "attractions are in the destination" (requires geocoding; see roadmap item 4).
- Input guardrails are simple rules only, with no model-based injection detection; they do not aim to stop every attack.

## Decisions

1. **An embedding failure is treated as "no match" and takes the existing empty-data fallback path** (`family`, `confidence_score=0.0`, `is_fallback=true`). Under the current routing, 0.0 goes to the retrieval branch, consistent with the safe default of "get more context when information is insufficient". Alternative: return an error and stop the workflow — this contradicts "CAG: fallback to default category" in DESIGN.md.

2. **On LLM failure, record only the exception type; do not put the raw exception text into the SSE event.** The event's `error` field says `"LLM call failed: <ExceptionType>"`; the full details go into the log, to avoid exposing API error details to the frontend.

3. **validate_output checks the status of the generate event first.** If it is `error`, it emits an error event directly, without parsing or calling the correction LLM.

4. **Structured output uses `response_mime_type="application/json"` plus `response_schema`, with the schema generated from `ItineraryOutput`.** The code-fence stripping logic is kept as a fallback (e.g. when switching models, or when the schema is not supported). Alternative: rely only on the JSON example in the prompt — this is what v0.1.0 does; its format failure rate is to be quantified by the evaluation.

5. **All business rules sit in one rule list after `parse_llm_output`; any rule failing counts as a validation failure and enters the existing corrective retry flow.** The error message states which rule and the concrete values, so the correction prompt can act on it. Each rule is a pure function, easy to test on its own.
   - **Days**: `len(daily_itinerary) == trip_length_days == requested trip_length`.
   - **Cost consistency**: `|Σ estimated_cost_aud − total_estimated_cost_aud| ≤ max(1 AUD, 1% of the total cost)`.
   - **Budget cap**: `total_estimated_cost_aud (per person) ≤ per-person daily cap[budget level] × number of days`; `luxury` has no cap.
   - **Unsupported specifics**: in the text fields (morning / afternoon / evening / key_tips), find two kinds of content — opening-hours statements (a time appearing together with open / opens / opening / close / closes) and currency amounts (`$25`, `AUD 30`, `A$40`, etc.). Each occurrence must appear in this request's knowledge context (ignoring case and whitespace), otherwise the rule fails. Numeric fields such as `estimated_cost_aud` are estimates and are not subject to this rule. Itinerary scheduling such as "depart at 9am" is not an opening-hours statement and is unaffected.

6. **Input guardrails sit in the request-validation layer before intake; on failure they return 422 with a reason code.** This way blocked requests consume no LLM calls, and the evaluation harness counts them as `refuse`.
   - **Out-of-scope destination**: the normalised destination must appear in `data/places/australia.tsv` (state names, capitals, major towns and tourist destinations; sourced from openly licensed place-name data). Each line of the file is "acceptable name → canonical lowercase English name"; Chinese names (悉尼, 墨尔本, 布里斯班, 黄金海岸, 凯恩斯, 珀斯, 阿德莱德, 霍巴特, 达尔文, 堪培拉, etc.) are added by hand. On a match the destination is replaced with the canonical name, so downstream retrieval and destination filtering only need to handle English names. The cost is that small places may be wrongly rejected, which the README states; roadmap items 3 (LLM request parsing) and 4 (Nominatim) can replace this approach.
     Alternative: English names only — `mixed_language` entries in the evaluation dataset that write the destination in Chinese would be rejected, and the behaviour correctness rate would actually drop.
   - **Prompt injection**: every free-text field is matched against a set of patterns, such as "ignore (all|previous) instructions", "system prompt", "you are now", and role markers (`<|...|>`, `### system`), ignoring case. The pattern list lives in configuration and can be extended. This is only a basic line of defence; its main purpose is to have measurable cases in the evaluation dataset.

7. **The day-count guardrail compares against the user's requested `trip_length`** (read from the intake event); when the intake event cannot be read it falls back to checking internal consistency only.

8. **Where the "knowledge context" comes from**: validate_output takes each chunk's `chunk_text` from the `retrieved_context` of the `rag_retrieve` event and joins them as the comparison text for the "unsupported specifics" rule; it is empty when retrieval did not run. After `rebuild-rag`, chunks gain more fields but `chunk_text` stays the same, so this rule does not need to change with it.

9. **Costs are always computed as "per person, in AUD".** Both the generation and the correction templates say so; the budget cap uses the "per person per day" caps that `build-evaluation-harness` defines in `config.py`. Template text is changed by adding new versions (old versions are not edited); old versions are kept so v0.1.0 results can be reproduced with `template_version`.

10. **Only one active version is allowed per template key.**
    - Database layer: a new migration creates the partial unique index `UNIQUE (template_key) WHERE is_active` on `prompt_templates`.
    - Seed layer: for each key, insert all missing versions, then in the same transaction first set older versions inactive and then set the highest version active.
    - The original "Seeded templates" requirement hardcoded "3 rows", which stops being true as soon as a template is upgraded, so it is replaced by "Seeded template set", which does not depend on a specific count. Later changes (e.g. `rebuild-rag`) that add template versions do not need to change this requirement again.

11. **The low-confidence case in the golden test**: change the destination from `"abcdefg hi"` to a valid Australian place name (e.g. `"alice springs"`), still using a rare travel_style to produce low confidence. During implementation, actually run it once to confirm the confidence really is below 0.85.

12. **Agno telemetry is off by default in code, with the environment variable as the override.** `travel_workflow` is constructed with `telemetry=False`, so every environment (local, deployment, evaluation runs) is off without depending on each machine's `.env`. `.env.example` gets a commented-out `AGNO_TELEMETRY=false` explaining that, when set, it overrides the code for every Agno instance — which matters once roadmap item 4 adds an `Agent`, since each Agno instance has its own `telemetry` flag. The conftest setting stays as a safety net for tests.
    Alternative: rely on `AGNO_TELEMETRY` in `.env` only — any environment that forgets it would silently send telemetry.

## Risks / Trade-offs

- [Embedding failures are masked by the fallback and hard to notice] → Log at error level, write `error_type="embedding_failed"` to the trace, and set `is_fallback=true` in the event.
- [Stricter rules raise the retry rate and latency] → This is exactly the cost to quantify with the evaluation harness; the report compares retry rate, error rate and p95 latency.
- [The regexes for opening hours and amounts may produce false positives or misses] → Write unit tests for every pattern; the faithfulness metric in the evaluation can reveal misses.
- [The high-confidence path has no knowledge context, so any specific price is judged unsupported] → This is the intended behaviour: prices without support should not appear in the first place. The correction prompt asks for them to be removed.
- [The place-name table wrongly rejects valid small places] → State this in the README; add one small-place entry to the evaluation dataset to observe it; the roadmap has alternatives.
- [The partial unique index migration fails on a database that already has two active versions] → The migration first sets every active row except the highest version of each key inactive, then creates the index.
- [`response_schema` does not support some Pydantic features] → Experiment with the current `ItineraryOutput` before implementing; if there are problems, hand-write an equivalent schema.
