# itinerary-generation Specification

## Purpose
Defines the `generate` step: resolving the single versioned prompt template `itinerary_with_context` from the database (the active version, or the version a request names), filling its variables from the request and upstream step outputs, including the retrieved chunks numbered as citation ids, and calling the LLM to produce the raw itinerary. Prompts are never hardcoded; every run records which template key and version it used.

## Requirements

### Requirement: Template resolution from the database
Templates SHALL be read from the `prompt_templates` table. When no `template_version` override is supplied, the step SHALL use the row matching the template key with `is_active` = true. When an override is supplied, the step SHALL use the row matching the template key and that exact version, regardless of `is_active`.

#### Scenario: Active version
- **WHEN** no `template_version` is supplied
- **THEN** the active row for the selected key is used

#### Scenario: Version override
- **WHEN** `template_version` = 2 is supplied and version 2 exists but is inactive
- **THEN** version 2 is used

### Requirement: Template variable substitution
The step SHALL substitute `{destination}`, `{trip_length}`, `{budget}`, `{travel_style}`, `{notes}`, `{matched_category}`, `{tone}`, `{constraints}`, `{retrieved_context}`, and `{daily_budget_ceiling}` in the template text, using an empty string for `{notes}` when the request has no notes. `{daily_budget_ceiling}` SHALL be the request's daily budget ceiling written as `"<amount> AUD per person per day, excluding accommodation"`, or `"none set"` when the request has no ceiling. Only placeholders that are valid identifiers and have a known value SHALL be replaced; unknown placeholders and other literal braces (such as the JSON schema example in the template) SHALL be left unchanged.

#### Scenario: JSON example preserved
- **WHEN** the template contains `{destination}` and a literal JSON example `{"day": integer}`
- **THEN** `{destination}` is replaced and the JSON example is unchanged

#### Scenario: Notes substituted
- **WHEN** the request has `notes` = `"kids love animals"` and the template contains `{notes}`
- **THEN** the resolved prompt contains `"kids love animals"`

#### Scenario: No notes
- **WHEN** the request has no notes and the template contains `{notes}`
- **THEN** `{notes}` is replaced with an empty string

#### Scenario: Ceiling from the level
- **WHEN** a `moderate` request without `max_daily_budget_aud` is generated with a template containing `{daily_budget_ceiling}`
- **THEN** the resolved prompt states the `moderate` default as AUD per person per day, excluding accommodation

#### Scenario: No ceiling
- **WHEN** a `luxury` request without `max_daily_budget_aud` is generated with a template containing `{daily_budget_ceiling}`
- **THEN** the placeholder is replaced with `"none set"`

### Requirement: LLM call
The step SHALL send the resolved prompt to the Gemini model named by `LLM_MODEL` (default `gemini-3.1-flash-lite`), requesting JSON output constrained by a response schema generated from `ItineraryOutput`, and SHALL pass the response text through unmodified as `raw_llm_output`.

#### Scenario: Default model
- **WHEN** `LLM_MODEL` is unset
- **THEN** `gemini-3.1-flash-lite` is called

#### Scenario: Structured output requested
- **WHEN** the generate step calls the LLM
- **THEN** the request specifies a JSON response type and the `ItineraryOutput` response schema

### Requirement: Generate event and trace
On success the generate event `data` SHALL contain `raw_llm_output`, `prompt_template_key`, and `prompt_template_version`, and the trace row SHALL record the same `prompt_template_key` and `prompt_template_version`.

#### Scenario: Template recorded
- **WHEN** generate succeeds using `itinerary_with_context` version 1
- **THEN** both the event and the trace row show key `itinerary_with_context` and version 1

### Requirement: LLM call failure
If the LLM call raises an exception, the generate step SHALL log it, SHALL emit an event with `status` = `"error"` and `error` = `"LLM call failed: <exception type>"` without the raw exception message, and SHALL write a trace row with `status` = `"error"`, the template key and version used, and `error_type` = `"llm_call_failed"`. The step SHALL NOT raise.

#### Scenario: Gemini returns an error
- **WHEN** the LLM API raises during generation
- **THEN** the generate event has `status` = `"error"` and `error` starts with `"LLM call failed:"`
- **AND** the request still completes with a `validate_output` event

### Requirement: Cost unit in templates
Every active generation template and the `validate_output_correction` template SHALL state that all costs are estimated in AUD per person, excluding accommodation.

#### Scenario: Active templates state the unit
- **WHEN** the seed has run
- **THEN** every active template text contains the phrase "AUD per person, excluding accommodation"

### Requirement: Budget ceiling in generation templates
Every active generation template SHALL contain the `{daily_budget_ceiling}` placeholder and ask that the total cost stay within it.

#### Scenario: Active generation templates state the ceiling
- **WHEN** the seed has run
- **THEN** every active generation template text contains `{daily_budget_ceiling}`

### Requirement: Seeded template set
`scripts/seed.py` SHALL define every template version separately from a declaration of the version in use for each key. It SHALL insert every defined `(template_key, version)` that is not yet in the database, and SHALL make the declared version of each key the only active one. If a declared version is not defined, the seed SHALL exit with an error before writing anything.

#### Scenario: Fresh database
- **WHEN** the seed script runs on empty tables
- **THEN** every defined version is present and, for each key, only the declared version is active

#### Scenario: New version added
- **WHEN** the seed defines version 2 of a key whose version 1 is active in the database, and declares version 2
- **THEN** after the seed runs, version 2 is active and version 1 is inactive

#### Scenario: Rolling back
- **WHEN** version 2 of a key is active and the declaration for that key is changed back to version 1
- **THEN** after the seed runs, version 1 is active, version 2 is inactive, and both rows are still present

#### Scenario: Declared version not defined
- **WHEN** the declaration names a version that has no definition
- **THEN** the seed exits with an error and `prompt_templates` is unchanged

### Requirement: Single active template version
The database SHALL allow at most one row with `is_active` = true per `template_key`.

#### Scenario: Second active row rejected
- **WHEN** an insert or update would make two rows with the same `template_key` active
- **THEN** the database rejects the write

### Requirement: Single generation template
The generate step SHALL use the template key `itinerary_with_context` for every request, resolved by the existing rules (the active version, or the exact `template_version` override). This template SHALL contain the `{retrieved_context}` and `{notes}` placeholders.

#### Scenario: Any confidence
- **WHEN** the intent confidence is 0.95 or 0.20
- **THEN** the selected template key is `itinerary_with_context`

### Requirement: Missing template error
If the selected template cannot be found, the step SHALL emit an event with `status` = `"error"` and `error` = `"No active template found for key '<key>'"`, SHALL write a trace row with `status` = `"error"`, and SHALL NOT call the LLM.

#### Scenario: Template table empty
- **WHEN** `prompt_templates` has no row for `itinerary_with_context`
- **THEN** the generate event has `status` = `"error"` and the LLM is not called

### Requirement: Retrieved context rendering
`{retrieved_context}` SHALL be rendered by numbering the retrieved chunks in order as citation ids `S1`, `S2`, … and rendering each as `"[S{n}] {title}\n{chunk_text}"`, joined by blank lines; it SHALL be the empty string when retrieval returned no chunks.

#### Scenario: Citation ids assigned
- **WHEN** three chunks are retrieved
- **THEN** the rendered context starts its blocks with `[S1]`, `[S2]`, and `[S3]` in retrieval order

#### Scenario: Retrieval returned nothing
- **WHEN** retrieval degraded to an empty list
- **THEN** `{retrieved_context}` is replaced with an empty string

### Requirement: Context sources in generate event
The generate event `data` SHALL include `context_sources`, a list with one entry per citation id `{"id", "chunk_id", "title", "source", "section"}` for every chunk placed in the prompt, or an empty list when no chunks were retrieved.

#### Scenario: Sources listed
- **WHEN** three chunks are placed in the prompt
- **THEN** `context_sources` has three entries with ids `S1`, `S2`, and `S3`

#### Scenario: No chunks retrieved
- **WHEN** retrieval returned no chunks
- **THEN** `context_sources` is an empty list
