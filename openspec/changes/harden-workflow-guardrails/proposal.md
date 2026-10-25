# Proposal

## Why

v0.1.0 only checks whether the output "looks like the right format"; nothing protects whether the content is correct, and the input is completely unguarded. Specifically:

- **Error handling does not match DESIGN.md section 10**: a failed embedding call in intent matching crashes the whole request; exceptions from the LLM calls in generate and validate_output are not caught; when a fallback template is used, the event and trace still record the original template key; the day-count guardrail only compares against the number of days the LLM reports itself.
- **Output is parsed as JSON after stripping markdown code fences**, even though Gemini supports schema-constrained JSON output natively.
- **Business rules rely entirely on the LLM behaving**: the daily costs do not necessarily add up to the total cost, the total may exceed the budget level, and the model may invent opening hours and prices that are not in the retrieved material.
- **No input guardrails**: asking about a foreign city still produces an itinerary; prompt injection in free-text fields is spliced into the prompt verbatim.

## What Changes

- **Error handling**: fall back to the default category when embedding fails; emit a structured error event when an LLM call fails; the trace records the template actually used; when generate has already failed, validate_output no longer does pointless validation and retries.
- **Native structured output**: both the generate call and the corrective retry call request JSON with Gemini's `response_schema` (generated from `ItineraryOutput`); the code-fence stripping logic is kept as a fallback.
- **Business rule checks** (a failure enters the existing corrective retry flow):
  - The number of days matches the number of days the user requested
  - The sum of daily costs equals the total cost (a small tolerance is allowed)
  - The total cost does not exceed the cap for the budget level
  - No opening hours or prices appear that are absent from the knowledge context
- **Input guardrails**: return 422 (`destination_out_of_scope`) when the destination is not in the Australian place-name table; the table holds both English names and common Chinese names (e.g. "悉尼"), and a match is replaced with the canonical English name. Return 422 (`input_rejected`) when a free-text field matches a prompt injection pattern.
- **Cost unit**: the generation and correction templates state explicitly that "all costs are per person, in AUD, excluding accommodation", and the budget rule is computed per person.
- **Template versions**: when seed adds a new version, older versions are automatically set inactive; the database guarantees at most one active version per template key (today, upgrading a template leaves two active versions, and `resolve_template` returns either one).
- **Agno telemetry off**: `travel_workflow` is created with `telemetry=False`, so `POST /generate` no longer sends a run event to `os-api.agno.com` on every request; `.env.example` documents `AGNO_TELEMETRY` as the override that applies to every Agno instance.
- Fix outdated code comments; replace the destination `"abcdefg hi"` used in the golden test to produce low confidence with a valid Australian place name (otherwise the new destination guardrail would reject it).

"Attractions really are in the destination" is **not checked at runtime in this change**: without geocoding only the LLM itself could judge it, which is unreliable. In this change it is measured by the evaluation harness's judge model; once roadmap item 4 integrates OpenStreetMap / Nominatim, it becomes a code check.

## Capabilities

### New Capabilities

(None)

### Modified Capabilities

- `intent-routing`: add a fallback for embedding failure.
- `itinerary-generation`: missing-template handling (record the template actually used); LLM calls switch to schema-constrained output; add LLM call failure handling; add the cost unit, template version activation rules and the "only one active version per key" constraint (replacing the original "Seeded templates").
- `output-validation`: parsing approach; day-count guardrail; add three rules — cost consistency, budget cap, unsupported specifics; add handling for upstream generation failure and correction call failure.
- `travel-workflow`: add input guardrails.

## Impact

- `steps/cag_match.py`, `steps/generate.py`, `steps/validate_output.py`, `output_validator.py`, `intake_model.py` or a new `input_guard.py`, `steps/rag_retrieve.py` (comments only)
- New `data/places/australia.tsv` (name → canonical English name; from openly licensed place-name data, with Chinese names added by hand; the licence is stored in the same directory)
- New Alembic migration: a partial unique index on `prompt_templates` (`template_key` WHERE `is_active`)
- `scripts/seed.py`: bump the template definitions to new versions (adding the "per person" wording), and handle them as "the highest version of each key is active"
- `tests/test_golden.py`: use a valid destination for the low-confidence case
- `travel_workflow.py` (`telemetry=False`), `.env.example` (`AGNO_TELEMETRY` documented)
- Reuse the per-budget-level daily cost caps that `build-evaluation-harness` defines in `config.py`
- New `error_type` values appear in traces; the API adds two 422 reason codes
- **Dependencies**: after `build-evaluation-harness` (needed to measure the change before and after)

**Success criteria** (measured with the evaluation harness, compared against the v0.1.0 baseline)

- The "correct number of days" and "within budget" parts of the constraint satisfaction rate reach 100% (non-compliant outputs are either corrected or end with a structured error).
- Faithfulness improves.
- The behaviour correctness rate of `out_of_scope` entries improves; all injection tests are blocked; the behaviour correctness rate of `mixed_language` entries does not drop.
- Report the change in retry rate and latency — stricter rules are expected to raise the retry rate, and the cost must be stated; any gate thresholds adjusted because of this are recorded in `docs/experiments.md`.
