# output-validation Specification

## Purpose
Defines the `validate_output` step: parsing the raw LLM output into a structured itinerary, enforcing the schema and a content guardrail, retrying once with a corrective prompt on failure, and reporting degraded or failed outcomes as structured events instead of unhandled exceptions.

## Requirements

### Requirement: Output schema
A valid itinerary SHALL conform to `ItineraryOutput`: `destination` (string), `trip_length_days` (integer), `budget_level` (string), `travel_style` (string), `daily_itinerary` (list of items with `day` integer, `morning` / `afternoon` / `evening` strings, and `estimated_cost_aud` number), `total_estimated_cost_aud` (number), and `key_tips` (list of strings).

#### Scenario: Missing field
- **WHEN** the parsed JSON has no `key_tips`
- **THEN** validation fails with the Pydantic error message

### Requirement: Parsing
The step SHALL read `raw_llm_output` from the generate event (empty string if unavailable), strip a surrounding markdown code fence (an opening line starting with ```` ``` ```` and a closing ```` ``` ```` line) if present, then parse the remainder as JSON before schema validation.

#### Scenario: Fenced JSON
- **WHEN** the LLM returns the JSON wrapped in a ```` ```json ```` fence
- **THEN** the fence is removed and the JSON is validated

#### Scenario: Not JSON
- **WHEN** the output is not valid JSON (including when it is empty)
- **THEN** validation fails with an error beginning `"JSON parse error:"`

### Requirement: Day-count guardrail
After schema validation passes, the step SHALL require the number of `daily_itinerary` entries to equal `trip_length_days`; a mismatch SHALL be treated as a validation failure.

#### Scenario: Day count mismatch
- **WHEN** `trip_length_days` is 5 and `daily_itinerary` has 4 entries
- **THEN** validation fails with a message beginning `"Content guardrail failed:"`

### Requirement: First-attempt success
When the first validation succeeds, the step SHALL emit `status` = `"completed"` with `data` = `{"itinerary": <validated object>, "degraded_mode": false}` and SHALL record `degraded_mode` = false in the trace row. No further LLM call is made.

#### Scenario: Valid output
- **WHEN** the generate output is a valid itinerary
- **THEN** the validate_output event has `degraded_mode` = `false`

### Requirement: Single corrective retry
When the first validation fails, the step SHALL resolve the active `validate_output_correction` template, substitute `{validation_errors}` and `{raw_llm_output}` with the first-attempt error and the original output, call the LLM exactly once with that prompt, and validate the new output with the same rules.

#### Scenario: Retry happens once
- **WHEN** the first validation fails
- **THEN** exactly one corrective LLM call is made, whatever its result

### Requirement: Retry outcome reporting
If the retry output is valid, the step SHALL emit `status` = `"completed"` with `data` = `{"itinerary": ..., "degraded_mode": true}` and trace `error_type` = `"validation_retry_succeeded"`. If the retry output is also invalid, the step SHALL emit `status` = `"error"`, `data` = `{"degraded_mode": true}`, `error` = `"Validation failed after retry: <errors>"`, and trace `error_type` = `"validation_failed_after_retry"`.

#### Scenario: Retry succeeds
- **WHEN** the first output is invalid and the corrected output is valid
- **THEN** the event is `completed` with `degraded_mode` = `true`

#### Scenario: Retry fails
- **WHEN** both outputs are invalid
- **THEN** the event is `error` with `degraded_mode` = `true` and no exception is raised

### Requirement: Correction template unavailable
If the first validation fails and no active `validate_output_correction` template exists, the step SHALL NOT call the LLM and SHALL emit `status` = `"error"`, `data` = `{"degraded_mode": true}`, `error` = `"Validation failed and correction template unavailable: <errors>"`, with trace `error_type` = `"correction_template_unavailable"`.

#### Scenario: Missing correction template
- **WHEN** validation fails and the correction template is not in the database
- **THEN** the event is `error` with `degraded_mode` = `true` and no retry is attempted
