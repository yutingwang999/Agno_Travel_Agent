## REMOVED Requirements

### Requirement: Template selection by confidence
**Reason**: Every request now retrieves knowledge, so a separate "minimal context" template without a knowledge placeholder is no longer used.
**Migration**: See "Single generation template" below. The old templates remain in the database and can still be pinned with `template_version` to reproduce earlier runs.

### Requirement: Missing template handling
**Reason**: With a single generation template there is no fallback key to try.
**Migration**: See "Missing template error" below.

### Requirement: Retrieved context formatting
**Reason**: The context now carries citation ids, and retrieval is never skipped.
**Migration**: See "Retrieved context rendering" below.

## MODIFIED Requirements

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

### Requirement: Generate event and trace
On success the generate event `data` SHALL contain `raw_llm_output`, `prompt_template_key`, and `prompt_template_version`, and the trace row SHALL record the same `prompt_template_key` and `prompt_template_version`.

#### Scenario: Template recorded
- **WHEN** generate succeeds using `itinerary_with_context` version 1
- **THEN** both the event and the trace row show key `itinerary_with_context` and version 1

## ADDED Requirements

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
