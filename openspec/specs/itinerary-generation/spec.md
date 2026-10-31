# itinerary-generation Specification

## Purpose
Defines the `generate` step: selecting a versioned prompt template from the database based on CAG confidence, resolving its variables from upstream step outputs, and calling the LLM to produce the raw itinerary. Prompts are never hardcoded; every run records which template key and version it used.

## Requirements

### Requirement: Template selection by confidence
The generate step SHALL select `high_confidence_minimal_context` when the cag_match `confidence_score` is at or above 0.85, and `low_confidence_with_retrieval` otherwise. A missing or unparseable score SHALL be treated as 0.0.

#### Scenario: High confidence
- **WHEN** `confidence_score` is 0.90
- **THEN** the selected template key is `high_confidence_minimal_context`

#### Scenario: Low confidence
- **WHEN** `confidence_score` is 0.40
- **THEN** the selected template key is `low_confidence_with_retrieval`

### Requirement: Template resolution from the database
Templates SHALL be read from the `prompt_templates` table. When no `template_version` override is supplied, the step SHALL use the row matching the template key with `is_active` = true. When an override is supplied, the step SHALL use the row matching the template key and that exact version, regardless of `is_active`.

#### Scenario: Active version
- **WHEN** no `template_version` is supplied
- **THEN** the active row for the selected key is used

#### Scenario: Version override
- **WHEN** `template_version` = 2 is supplied and version 2 exists but is inactive
- **THEN** version 2 is used

### Requirement: Missing template handling
If the selected template cannot be found, the step SHALL retry resolution with `low_confidence_with_retrieval` using the same version parameter, and when that succeeds SHALL report `low_confidence_with_retrieval` and its version as the template actually used, in both the event and the trace row. If that also cannot be found (or was already the selected key), the step SHALL emit an event with `status` = `"error"` and `error` = `"No active template found for key '<selected key>'"`, SHALL write a trace row with `status` = `"error"`, and SHALL NOT call the LLM.

#### Scenario: Template table empty
- **WHEN** `prompt_templates` has no matching rows
- **THEN** the generate event has `status` = `"error"` and the LLM is not called

#### Scenario: Fallback template recorded
- **WHEN** `high_confidence_minimal_context` is selected but missing, and `low_confidence_with_retrieval` version 1 exists
- **THEN** the generate event and trace row both show `prompt_template_key` = `"low_confidence_with_retrieval"` and `prompt_template_version` = 1

### Requirement: Template variable substitution
The step SHALL substitute `{destination}`, `{trip_length}`, `{budget}`, `{travel_style}`, `{matched_category}`, `{tone}`, `{constraints}`, `{retrieved_context}`, and `{daily_budget_ceiling}` in the template text. `{daily_budget_ceiling}` SHALL be the request's daily budget ceiling written as `"<amount> AUD per person per day, excluding accommodation"`, or `"none set"` when the request has no ceiling. Only placeholders that are valid identifiers and have a known value SHALL be replaced; unknown placeholders and other literal braces (such as the JSON schema example in the template) SHALL be left unchanged.

#### Scenario: JSON example preserved
- **WHEN** the template contains `{destination}` and a literal JSON example `{"day": integer}`
- **THEN** `{destination}` is replaced and the JSON example is unchanged

#### Scenario: Ceiling from the level
- **WHEN** a `moderate` request without `max_daily_budget_aud` is generated with a template containing `{daily_budget_ceiling}`
- **THEN** the resolved prompt states the `moderate` default as AUD per person per day, excluding accommodation

#### Scenario: No ceiling
- **WHEN** a `luxury` request without `max_daily_budget_aud` is generated with a template containing `{daily_budget_ceiling}`
- **THEN** the placeholder is replaced with `"none set"`

### Requirement: Retrieved context formatting
`retrieved_context` SHALL be rendered as each chunk's `"[title]\nchunk_text"` (or just `chunk_text` when the title is empty), joined by blank lines. When `rag_retrieve` did not run or returned no chunks, it SHALL be the empty string.

#### Scenario: Retrieval skipped
- **WHEN** the high-confidence branch is taken
- **THEN** `{retrieved_context}` is replaced with an empty string

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
- **WHEN** generate succeeds using `high_confidence_minimal_context` version 1
- **THEN** both the event and the trace row show key `high_confidence_minimal_context` and version 1

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
