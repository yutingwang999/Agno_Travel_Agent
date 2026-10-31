# Proposal

## Why

v0.1.0 only checks whether the output "looks like the right format"; nothing protects whether the content is correct, and the input is completely unguarded. Specifically:

- **Error handling does not match DESIGN.md section 10**: a failed embedding call in intent matching crashes the whole request; exceptions from the LLM calls in generate and validate_output are not caught; when a fallback template is used, the event and trace still record the original template key; the day-count guardrail only compares against the number of days the LLM reports itself.
- **Output is parsed as JSON after stripping markdown code fences**, even though Gemini supports schema-constrained JSON output natively.
- **Business rules rely entirely on the LLM behaving**: the daily costs do not necessarily add up to the total cost, the total may exceed the budget level, and the model may invent opening hours and prices that are not in the retrieved material.
- **The budget is only a word**: the prompt says "a moderate budget" with no amount and no unit, so the model cannot know what the evaluation (and this change's budget rule) holds it to; and the three levels give the user no way to state their own amount — a `luxury` trip has no ceiling at all (the v0.1.0 baseline has luxury itineraries at 6,500–12,000 AUD per person per day).
- **No input guardrails**: asking about a foreign city still produces an itinerary; prompt injection in free-text fields is spliced into the prompt verbatim.

## What Changes

- **Error handling**: fall back to the default category when embedding fails; emit a structured error event when an LLM call fails; the trace records the template actually used; when generate has already failed, validate_output no longer does pointless validation and retries.
- **Native structured output**: both the generate call and the corrective retry call request JSON with Gemini's `response_schema` (generated from `ItineraryOutput`); the code-fence stripping logic is kept as a fallback.
- **Business rule checks** (a failure enters the existing corrective retry flow):
  - The number of days matches the number of days the user requested
  - The sum of daily costs equals the total cost (a small tolerance is allowed)
  - The total cost does not exceed the request's daily budget ceiling times the number of days
  - No opening hours or prices appear that are absent from the knowledge context
- **User-set budget ceiling**: `POST /generate` accepts an optional `max_daily_budget_aud` (AUD per person per day, excluding accommodation) for any budget level, with an input box in the form. The request's ceiling is that amount when given, otherwise the level's default (`budget` 70, `moderate` 200, `luxury` none). The three levels stay, as the travel style the amount cannot express. The generation templates state the ceiling, and a budget rule failure states the ceiling and the actual total, so both the first call and the correction know the number.
- **Input guardrails**: return 422 (`destination_out_of_scope`) when the destination is not in the Australian place-name table (also when it is too vague to look up, such as "Australia"; the message asks for a specific place); the table is built from GeoNames plus hand-kept lists, holds English names and common Chinese names in Simplified and Traditional script (e.g. "悉尼", "墨爾本"), and a match is replaced with the canonical English name. Return 422 (`input_rejected`) when a free-text field matches a prompt injection pattern.
- **Cost unit**: the generation and correction templates state explicitly that "all costs are per person, in AUD, excluding accommodation", and the budget rule is computed per person.
- **Template versions**: seed declares the version in use per key (`ACTIVE_TEMPLATE_VERSIONS`) and makes exactly that version active, so both upgrading and rolling back are a one-line change with no duplicate rows; the database guarantees at most one active version per template key (today, upgrading a template leaves two active versions, and `resolve_template` returns either one).
- **Agno telemetry off**: `travel_workflow` is created with `telemetry=False`, so `POST /generate` no longer sends a run event to `os-api.agno.com` on every request; `.env.example` documents `AGNO_TELEMETRY` as the override that applies to every Agno instance.
- Fix outdated code comments; replace the destination `"abcdefg hi"` used in the golden test to produce low confidence with a valid Australian place name (otherwise the new destination guardrail would reject it).

"Attractions really are in the destination" is **not checked at runtime in this change**: without geocoding only the LLM itself could judge it, which is unreliable. In this change it is measured by the evaluation harness's judge model; once roadmap item 4 integrates OpenStreetMap / Nominatim, it becomes a code check.

## Capabilities

### New Capabilities

(None)

### Modified Capabilities

- `intent-routing`: add a fallback for embedding failure.
- `itinerary-generation`: missing-template handling (record the template actually used); LLM calls switch to schema-constrained output; add LLM call failure handling; add the cost unit, the budget ceiling placeholder, template version activation rules and the "only one active version per key" constraint (replacing the original "Seeded templates").
- `output-validation`: parsing approach; day-count guardrail; add three rules — cost consistency, budget ceiling, unsupported specifics; add handling for upstream generation failure and correction call failure.
- `travel-workflow`: add input guardrails; the request and the intake event gain the optional `max_daily_budget_aud`.
- `evaluation-harness`: dataset entries may carry `max_daily_budget_aud`, and the budget constraint uses the request's ceiling.

## Impact

- `steps/cag_match.py`, `steps/generate.py`, `steps/validate_output.py`, `output_validator.py`, `intake_model.py` or a new `input_guard.py`, `steps/rag_retrieve.py` (comments only)
- New `data/places/australia.tsv` (name → canonical English name), built by a new `scripts/build_places.py` from GeoNames `cities1000` (CC BY 4.0; the downloaded file stays out of git under `data/places/raw/`) and hand-kept lists of states, tourist destinations and Chinese names; the source and licence note is stored in the same directory
- New Alembic migration: a partial unique index on `prompt_templates` (`template_key` WHERE `is_active`)
- `scripts/seed.py`: add new template versions (the "per person" wording, then the budget ceiling) and an `ACTIVE_TEMPLATE_VERSIONS` map that decides which version of each key is active
- `tests/test_golden.py`: use a valid destination for the low-confidence case
- `travel_workflow.py` (`telemetry=False`), `.env.example` (`AGNO_TELEMETRY` documented)
- Reuse the per-budget-level daily cost caps that `build-evaluation-harness` defines in `config.py`, now as the defaults when the request gives no amount
- **Public API changes** (confirmed with the user 2026-10-28): two 422 reason codes with the rejection body; the optional request field `max_daily_budget_aud` and the same field in the intake event; `docs/api.md`, the README and the form (`src/app/static/index.html`) change with them
- New `error_type` values appear in traces
- Evaluation: `src/evaluation` reads the new form field; the dataset gains entries with it (dataset v2, recorded in the dataset change log)
- **Dependencies**: after `build-evaluation-harness` (needed to measure the change before and after)

**Success criteria** (measured with the evaluation harness, compared against the v0.1.0 baseline)

- The "correct number of days" and "within budget" parts of the constraint satisfaction rate reach 100% (non-compliant outputs are either corrected or end with a structured error).
- Faithfulness improves.
- The behaviour correctness rate of `out_of_scope` entries improves; every `prompt_injection` entry whose injection is in a request field is blocked (e058, whose injection is in `form.notes`, is not applicable until `rebuild-rag` adds the field); the behaviour correctness rate of `mixed_language` entries does not drop.
- The effect of stating the budget is reported in steps: the cost-unit wording alone, then the ceiling in the prompt, then the rules — so the change in "within budget" can be attributed.
- Report the change in retry rate and latency — stricter rules are expected to raise the retry rate, and the cost must be stated; any gate thresholds adjusted because of this are recorded in `docs/experiments.md`.
