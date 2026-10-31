## MODIFIED Requirements

### Requirement: Parsing
The step SHALL read `raw_llm_output` from the generate event (empty string if unavailable), strip a surrounding markdown code fence (an opening line starting with ```` ``` ```` and a closing ```` ``` ```` line) if present as a fallback for providers that ignore the response schema, then parse the remainder as JSON before schema validation. The corrective retry call SHALL request JSON output with the same `ItineraryOutput` response schema as the generate step.

#### Scenario: Fenced JSON
- **WHEN** the LLM returns the JSON wrapped in a ```` ```json ```` fence
- **THEN** the fence is removed and the JSON is validated

#### Scenario: Not JSON
- **WHEN** the output is not valid JSON (including when it is empty)
- **THEN** validation fails with an error beginning `"JSON parse error:"`

#### Scenario: Corrective call uses the schema
- **WHEN** the corrective retry calls the LLM
- **THEN** the request specifies a JSON response type and the `ItineraryOutput` response schema

### Requirement: Day-count guardrail
After schema validation passes, the step SHALL require the number of `daily_itinerary` entries to equal `trip_length_days`, and SHALL require `trip_length_days` to equal the requested `trip_length` from the intake event when that value is available; any mismatch SHALL be treated as a validation failure.

#### Scenario: Day count mismatch
- **WHEN** `trip_length_days` is 5 and `daily_itinerary` has 4 entries
- **THEN** validation fails with a message beginning `"Content guardrail failed:"`

#### Scenario: Output disagrees with the request
- **WHEN** the user requested `trip_length` = 5 but the output has `trip_length_days` = 3 and 3 daily entries
- **THEN** validation fails with a message beginning `"Content guardrail failed:"`

## ADDED Requirements

### Requirement: Cost consistency rule
After schema validation passes, the step SHALL require the sum of `daily_itinerary[].estimated_cost_aud` to differ from `total_estimated_cost_aud` by no more than the larger of 1 AUD and 1% of the total; otherwise validation SHALL fail with a message beginning `"Business rule failed: cost"`.

#### Scenario: Totals disagree
- **WHEN** the daily costs sum to 900 and `total_estimated_cost_aud` is 1,200
- **THEN** validation fails with a message beginning `"Business rule failed: cost"`

#### Scenario: Rounding tolerated
- **WHEN** the daily costs sum to 1,200.40 and the total is 1,200
- **THEN** the cost consistency rule passes

### Requirement: Budget ceiling rule
After schema validation passes, the step SHALL require `total_estimated_cost_aud`, interpreted as AUD per person excluding accommodation, to be no greater than the request's daily budget ceiling multiplied by the requested trip length, reading the budget level and `max_daily_budget_aud` from the intake event; a request without a daily ceiling SHALL pass. A violation SHALL fail validation with a message beginning `"Business rule failed: budget"`.

#### Scenario: Budget trip over the ceiling
- **WHEN** a 3-day `budget` request without an amount produces a total above 3 times the `budget` default
- **THEN** validation fails with a message beginning `"Business rule failed: budget"`

#### Scenario: User amount overrides the level
- **WHEN** a 2-day `moderate` request with `max_daily_budget_aud` = 120 produces a total of 300
- **THEN** validation fails with a message beginning `"Business rule failed: budget"`

#### Scenario: Luxury with an amount
- **WHEN** a 2-day `luxury` request with `max_daily_budget_aud` = 1500 produces a total of 5,000
- **THEN** validation fails with a message beginning `"Business rule failed: budget"`

#### Scenario: Luxury without an amount has no ceiling
- **WHEN** a `luxury` request without `max_daily_budget_aud` produces a very high total
- **THEN** the budget ceiling rule passes

### Requirement: Budget rule failure message
A budget ceiling rule failure message SHALL state the itinerary's total, the ceiling for the trip, and the daily ceiling and number of days the trip ceiling comes from, so that the corrective call knows the target.

#### Scenario: Message states the numbers
- **WHEN** a 3-day request with `max_daily_budget_aud` = 200 produces a total of 1,200
- **THEN** the failure message contains the total 1,200, the ceiling 600, and the 200-per-day and 3-day figures

### Requirement: Unsupported specifics rule
After schema validation passes, the step SHALL find opening-hours statements (a time stated together with open, opens, opening, close, or closes) and currency amounts in the text fields `morning`, `afternoon`, `evening`, and `key_tips`, and SHALL require each one to appear, ignoring case and whitespace, in the validation knowledge context; otherwise validation SHALL fail with a message beginning `"Business rule failed: unsupported"`. Numeric cost fields SHALL be exempt.

#### Scenario: Invented opening hours
- **WHEN** the itinerary says "the museum opens at 9:30am" and the knowledge context contains no such statement
- **THEN** validation fails with a message beginning `"Business rule failed: unsupported"`

#### Scenario: Schedule time is not an opening-hours statement
- **WHEN** the itinerary says "leave the hotel at 9am"
- **THEN** the unsupported specifics rule is not triggered by that phrase

#### Scenario: Price taken from the context
- **WHEN** the itinerary mentions "$25 entry" and the knowledge context contains "$25 entry"
- **THEN** the unsupported specifics rule passes for that phrase

### Requirement: Request budget figures are supported
The unsupported specifics rule SHALL treat the request's own budget figures as supported: its daily budget ceiling, and that ceiling multiplied by the requested trip length. A request without a daily ceiling has no such figures.

#### Scenario: Budget ceiling repeated
- **WHEN** a 5-day `budget` request without `max_daily_budget_aud` produces a tip "keep daily costs under 70 AUD" and the knowledge context has no prices
- **THEN** the unsupported specifics rule passes for that phrase

### Requirement: Validation knowledge context
The knowledge context used by validation rules SHALL be the `chunk_text` of every chunk in the `rag_retrieve` event, joined together, or the empty string when retrieval did not run or returned no chunks.

#### Scenario: Retrieval did not run
- **WHEN** the request took a branch without `rag_retrieve`
- **THEN** the validation knowledge context is empty, so any opening-hours statement or currency amount in the text fields fails the unsupported specifics rule

### Requirement: Upstream generation failure
If the generate event has `status` = `"error"`, the validate_output step SHALL NOT parse output or call the LLM, and SHALL emit `status` = `"error"`, `data` = `{"degraded_mode": true}`, and `error` = `"Generation failed upstream"`, with trace `error_type` = `"upstream_generation_failed"`.

#### Scenario: Generate step failed
- **WHEN** the generate event has `status` = `"error"`
- **THEN** the validate_output event has `status` = `"error"` and `error` = `"Generation failed upstream"`
- **AND** no corrective LLM call is made

### Requirement: Correction call failure
If the corrective LLM call raises an exception, the step SHALL log it and SHALL emit `status` = `"error"`, `data` = `{"degraded_mode": true}`, and `error` = `"Correction call failed: <exception type>"`, with trace `error_type` = `"correction_call_failed"`. The step SHALL NOT raise.

#### Scenario: Retry call errors
- **WHEN** the first validation fails and the corrective LLM call raises
- **THEN** the validate_output event has `status` = `"error"` and `degraded_mode` = `true`
- **AND** no exception propagates to the API layer
