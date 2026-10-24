## ADDED Requirements

### Requirement: Embedding failure fallback
If embedding the intent text or loading `itinerary_categories` raises an exception, the `cag_match` step SHALL log the error, SHALL report the same result as the empty-reference-data fallback (`matched_category` = `"family"`, `confidence_score` = 0.0, `tone` = `"friendly and helpful"`, `constraints` = `""`, `is_fallback` = `true`) with `status` = `"completed"`, and SHALL record `error_type` = `"embedding_failed"` in its trace row.

#### Scenario: Gemini embedding call fails
- **WHEN** the embedding API raises an error during `cag_match`
- **THEN** the cag_match event has `status` = `"completed"`, `confidence_score` = 0.0, and `is_fallback` = `true`
- **AND** the trace row for `cag_match` has `error_type` = `"embedding_failed"`
- **AND** the workflow continues to `retrieval_decision`
