## MODIFIED Requirements

### Requirement: Missing template handling
If the selected template cannot be found, the step SHALL retry resolution with `low_confidence_with_retrieval` using the same version parameter, and when that succeeds SHALL report `low_confidence_with_retrieval` and its version as the template actually used, in both the event and the trace row. If that also cannot be found (or was already the selected key), the step SHALL emit an event with `status` = `"error"` and `error` = `"No active template found for key '<selected key>'"`, SHALL write a trace row with `status` = `"error"`, and SHALL NOT call the LLM.

#### Scenario: Template table empty
- **WHEN** `prompt_templates` has no matching rows
- **THEN** the generate event has `status` = `"error"` and the LLM is not called

#### Scenario: Fallback template recorded
- **WHEN** `high_confidence_minimal_context` is selected but missing, and `low_confidence_with_retrieval` version 1 exists
- **THEN** the generate event and trace row both show `prompt_template_key` = `"low_confidence_with_retrieval"` and `prompt_template_version` = 1

### Requirement: LLM call
The step SHALL send the resolved prompt to the Gemini model named by `LLM_MODEL` (default `gemini-2.0-flash`), requesting JSON output constrained by a response schema generated from `ItineraryOutput`, and SHALL pass the response text through unmodified as `raw_llm_output`.

#### Scenario: Default model
- **WHEN** `LLM_MODEL` is unset
- **THEN** `gemini-2.0-flash` is called

#### Scenario: Structured output requested
- **WHEN** the generate step calls the LLM
- **THEN** the request specifies a JSON response type and the `ItineraryOutput` response schema

## REMOVED Requirements

### Requirement: Seeded templates
**Reason**: The fixed "3 rows" description no longer holds once templates gain new versions (starting with the per-person cost wording in this change).
**Migration**: See "Seeded template set" and "Single active template version" below.

## ADDED Requirements

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

### Requirement: Seeded template set
`scripts/seed.py` SHALL insert every `(template_key, version)` it defines that is not yet in the database, and SHALL mark the highest defined version of each key as the active one.

#### Scenario: Fresh database
- **WHEN** the seed script runs on empty tables
- **THEN** every defined version is present and, for each key, only the highest version is active

#### Scenario: New version added
- **WHEN** the seed defines version 2 of a key whose version 1 is already active in the database
- **THEN** after the seed runs, version 2 is active and version 1 is inactive

### Requirement: Single active template version
The database SHALL allow at most one row with `is_active` = true per `template_key`.

#### Scenario: Second active row rejected
- **WHEN** an insert or update would make two rows with the same `template_key` active
- **THEN** the database rejects the write
