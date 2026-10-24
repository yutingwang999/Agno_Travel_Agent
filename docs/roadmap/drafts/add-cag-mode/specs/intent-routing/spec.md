## RENAMED Requirements

- FROM: `### Requirement: CAG match event`
- TO: `### Requirement: Intent match event`

## MODIFIED Requirements

### Requirement: Intent match event
The `intent_match` event `data` SHALL contain `matched_category`, `confidence_score`, `tone`, `constraints`, and `is_fallback`.

#### Scenario: Event payload
- **WHEN** `intent_match` completes
- **THEN** its event `data` has exactly those five keys

### Requirement: Intent text construction
The `intent_match` step SHALL build the intent text from the normalised request fields as `"{travel_style} trip to {destination} with {budget} budget"`.

#### Scenario: Family request
- **WHEN** the request is `travel_style` = `"family"`, `destination` = `"sydney"`, `budget` = `"moderate"`
- **THEN** the intent text is `"family trip to sydney with moderate budget"`

### Requirement: Intent embedding
The `intent_match` step SHALL embed the intent text with the Gemini model named by `EMBEDDING_MODEL` (default `gemini-embedding-001`), using task type `SEMANTIC_SIMILARITY` and 768 output dimensions — the same model and dimensionality used to embed categories at seed time.

#### Scenario: Embedding model matches seed
- **WHEN** `EMBEDDING_MODEL` is unset
- **THEN** both seeding and matching use `gemini-embedding-001` at 768 dimensions

### Requirement: In-memory category matching
The `intent_match` step SHALL load every row of `itinerary_categories` into memory and compute the cosine similarity between the intent embedding and each row's `embedding_vector` in-process, without issuing a vector similarity query to the database. Rows with a null embedding SHALL be skipped. The row with the highest similarity SHALL be the match, and that similarity SHALL be reported as `confidence_score`.

#### Scenario: Best match selected
- **WHEN** the highest similarity among categories is 0.91 for `family`
- **THEN** `matched_category` is `"family"` and `confidence_score` is 0.91
- **AND** `is_fallback` is `false`

### Requirement: Empty reference data fallback
When `itinerary_categories` has no rows, or every row has a null embedding, the step SHALL report `matched_category` = `"family"`, `confidence_score` = 0.0, `tone` = `"friendly and helpful"`, `constraints` = `""`, and `is_fallback` = `true`.

#### Scenario: Categories table is empty
- **WHEN** `itinerary_categories` contains no rows
- **THEN** the intent_match event has `confidence_score` = 0.0 and `is_fallback` = `true`
- **AND** the step status is `"completed"`

### Requirement: Embedding failure fallback
If embedding the intent text or loading `itinerary_categories` raises an exception, the `intent_match` step SHALL log the error, SHALL report the same result as the empty-reference-data fallback (`matched_category` = `"family"`, `confidence_score` = 0.0, `tone` = `"friendly and helpful"`, `constraints` = `""`, `is_fallback` = `true`) with `status` = `"completed"`, and SHALL record `error_type` = `"embedding_failed"` in its trace row.

#### Scenario: Gemini embedding call fails
- **WHEN** the embedding API raises an error during `intent_match`
- **THEN** the intent_match event has `status` = `"completed"`, `confidence_score` = 0.0, and `is_fallback` = `true`
- **AND** the trace row for `intent_match` has `error_type` = `"embedding_failed"`
- **AND** the workflow continues to `retrieval_decision`

## REMOVED Requirements

### Requirement: Retrieval routing threshold
**Reason**: Intent confidence measures how closely a request resembles an itinerary category, not whether destination knowledge is needed, and the 0.85 threshold had no experimental basis. Routing now depends on knowledge size.
**Migration**: See `knowledge-context` — "Knowledge mode decision" and "Configurable token budget". `RETRIEVAL_CONFIDENCE_THRESHOLD` is deleted.

### Requirement: Routing decision event
**Reason**: The decision event now reports the knowledge mode instead of a confidence-based routing decision.
**Migration**: See `knowledge-context` — "Knowledge mode event". Clients reading `data.routing_decision` must read `data.knowledge_mode` instead.
