## REMOVED Requirements

### Requirement: Template selection by confidence
**Reason**: Every generation now receives destination knowledge, so a separate "minimal context" template is no longer needed, and confidence no longer drives knowledge decisions.
**Migration**: See "Single knowledge template" below. The old templates stay in the database as inactive versions and can still be pinned with `template_version` for reproduction.

### Requirement: Missing template handling
**Reason**: With a single template there is no fallback key to try.
**Migration**: See "Missing template error" below.

### Requirement: Retrieved context formatting
**Reason**: The prompt variable now carries knowledge from either CAG or RAG, never an empty "skipped retrieval" context.
**Migration**: See "Knowledge context formatting" below; `{retrieved_context}` is renamed `{knowledge_context}`.

### Requirement: Generate event and trace
**Reason**: Its example relied on the removed high-confidence template, and the event now also records the knowledge mode.
**Migration**: See "Generate event records template and mode" below.

### Requirement: Seeded templates
**Reason**: The seeded template set changes.
**Migration**: See "Seeded prompt templates" below.

## MODIFIED Requirements

### Requirement: Template variable substitution
The step SHALL substitute `{destination}`, `{trip_length}`, `{budget}`, `{travel_style}`, `{notes}`, `{matched_category}`, `{tone}`, `{constraints}`, and `{knowledge_context}` in the template text, using an empty string for `{notes}` when the request has no notes. Only placeholders that are valid identifiers and have a known value SHALL be replaced; unknown placeholders and other literal braces (such as the JSON schema example in the template) SHALL be left unchanged.

#### Scenario: JSON example preserved
- **WHEN** the template contains `{destination}` and a literal JSON example `{"day": integer}`
- **THEN** `{destination}` is replaced and the JSON example is unchanged

#### Scenario: Notes substituted
- **WHEN** the request has `notes` = `"kids love animals"` and the template contains `{notes}`
- **THEN** the resolved prompt contains `"kids love animals"`

#### Scenario: No notes
- **WHEN** the request has no notes and the template contains `{notes}`
- **THEN** `{notes}` is replaced with an empty string

## ADDED Requirements

### Requirement: Single knowledge template
The generate step SHALL use the template key `itinerary_with_knowledge` for every request, resolved by the existing rules (active version, or the exact `template_version` override).

#### Scenario: Any confidence
- **WHEN** the intent confidence is 0.95 or 0.20
- **THEN** the selected template key is `itinerary_with_knowledge`

### Requirement: Missing template error
If the selected template cannot be found, the step SHALL emit an event with `status` = `"error"` and `error` = `"No active template found for key '<key>'"`, SHALL write a trace row with `status` = `"error"`, and SHALL NOT call the LLM.

#### Scenario: Template table empty
- **WHEN** `prompt_templates` has no row for `itinerary_with_knowledge`
- **THEN** the generate event has `status` = `"error"` and the LLM is not called

### Requirement: Knowledge context formatting
`{knowledge_context}` SHALL be built from the `cag_context` chunks in CAG mode or the `rag_retrieve` chunks in RAG mode, rendering each chunk as `"[title]\nchunk_text"` (or just `chunk_text` when the title is empty) joined by blank lines; it SHALL be the empty string only when the selected source returned no chunks.

#### Scenario: CAG mode
- **WHEN** the knowledge mode is `"cag"` and `cag_context` included 80 chunks
- **THEN** `{knowledge_context}` contains all 80 chunks

#### Scenario: RAG mode returns nothing
- **WHEN** the knowledge mode is `"rag"` and retrieval degraded to an empty list
- **THEN** `{knowledge_context}` is the empty string

### Requirement: Generate event records template and mode
On success the generate event `data` SHALL contain `raw_llm_output`, `prompt_template_key`, `prompt_template_version`, `knowledge_mode`, and `context_cached`, and the trace row SHALL record the same `prompt_template_key` and `prompt_template_version`.

#### Scenario: Template and mode recorded
- **WHEN** generate succeeds in CAG mode using `itinerary_with_knowledge` version 1
- **THEN** the event shows that key and version with `knowledge_mode` = `"cag"`, and the trace row shows the same key and version

### Requirement: Seeded prompt templates
`scripts/seed.py` SHALL seed `itinerary_with_knowledge` (active) and `validate_output_correction` (active), and SHALL keep `high_confidence_minimal_context` and `low_confidence_with_retrieval` as inactive versions, skipping any `(template_key, version)` pair that already exists.

#### Scenario: Fresh database
- **WHEN** the seed script runs on empty tables
- **THEN** the only active generation template is `itinerary_with_knowledge`
