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
If the selected template cannot be found, the step SHALL retry resolution with `low_confidence_with_retrieval` using the same version parameter. If that also cannot be found (or was already the selected key), the step SHALL emit an event with `status` = `"error"` and `error` = `"No active template found for key '<selected key>'"`, SHALL write a trace row with `status` = `"error"`, and SHALL NOT call the LLM.

#### Scenario: Template table empty
- **WHEN** `prompt_templates` has no matching rows
- **THEN** the generate event has `status` = `"error"` and the LLM is not called

### Requirement: Template variable substitution
The step SHALL substitute `{destination}`, `{trip_length}`, `{budget}`, `{travel_style}`, `{matched_category}`, `{tone}`, `{constraints}`, and `{retrieved_context}` in the template text. Only placeholders that are valid identifiers and have a known value SHALL be replaced; unknown placeholders and other literal braces (such as the JSON schema example in the template) SHALL be left unchanged.

#### Scenario: JSON example preserved
- **WHEN** the template contains `{destination}` and a literal JSON example `{"day": integer}`
- **THEN** `{destination}` is replaced and the JSON example is unchanged

### Requirement: Retrieved context formatting
`retrieved_context` SHALL be rendered as each chunk's `"[title]\nchunk_text"` (or just `chunk_text` when the title is empty), joined by blank lines. When `rag_retrieve` did not run or returned no chunks, it SHALL be the empty string.

#### Scenario: Retrieval skipped
- **WHEN** the high-confidence branch is taken
- **THEN** `{retrieved_context}` is replaced with an empty string

### Requirement: LLM call
The step SHALL send the resolved prompt to the Gemini model named by `LLM_MODEL` (default `gemini-3.1-flash-lite`) and SHALL pass the response text through unmodified as `raw_llm_output`.

#### Scenario: Default model
- **WHEN** `LLM_MODEL` is unset
- **THEN** `gemini-3.1-flash-lite` is called

### Requirement: Generate event and trace
On success the generate event `data` SHALL contain `raw_llm_output`, `prompt_template_key`, and `prompt_template_version`, and the trace row SHALL record the same `prompt_template_key` and `prompt_template_version`.

#### Scenario: Template recorded
- **WHEN** generate succeeds using `high_confidence_minimal_context` version 1
- **THEN** both the event and the trace row show key `high_confidence_minimal_context` and version 1

### Requirement: Seeded templates
`scripts/seed.py` SHALL seed the templates `high_confidence_minimal_context`, `low_confidence_with_retrieval`, and `validate_output_correction`, skipping any `(template_key, version)` pair that already exists.

#### Scenario: Fresh database
- **WHEN** the seed script runs on empty tables
- **THEN** `prompt_templates` contains 3 rows
