# intent-routing Specification

## Purpose
Defines the CAG side of the workflow: how the `cag_match` step classifies the user's intent into an itinerary category using embeddings over the preloaded `itinerary_categories` reference data, and how the `retrieval_decision` condition uses the resulting confidence score to decide whether RAG retrieval runs. CAG answers "what to generate"; RAG (see `knowledge-retrieval`) answers "what information to include".

## Requirements

### Requirement: Intent text construction
The `cag_match` step SHALL build the intent text from the normalised request fields as `"{travel_style} trip to {destination} with {budget} budget"`.

#### Scenario: Family request
- **WHEN** the request is `travel_style` = `"family"`, `destination` = `"sydney"`, `budget` = `"moderate"`
- **THEN** the intent text is `"family trip to sydney with moderate budget"`

### Requirement: Intent embedding
The `cag_match` step SHALL embed the intent text with the Gemini model named by `EMBEDDING_MODEL` (default `gemini-embedding-001`), using task type `SEMANTIC_SIMILARITY` and 768 output dimensions — the same model and dimensionality used to embed categories at seed time.

#### Scenario: Embedding model matches seed
- **WHEN** `EMBEDDING_MODEL` is unset
- **THEN** both seeding and matching use `gemini-embedding-001` at 768 dimensions

### Requirement: In-memory category matching
The `cag_match` step SHALL load every row of `itinerary_categories` into memory and compute the cosine similarity between the intent embedding and each row's `embedding_vector` in-process, without issuing a vector similarity query to the database. Rows with a null embedding SHALL be skipped. The row with the highest similarity SHALL be the match, and that similarity SHALL be reported as `confidence_score`.

#### Scenario: Best match selected
- **WHEN** the highest similarity among categories is 0.91 for `family`
- **THEN** `matched_category` is `"family"` and `confidence_score` is 0.91
- **AND** `is_fallback` is `false`

### Requirement: Low-similarity fallback
When the best similarity is below the minimum similarity of 0.30, the step SHALL report the `family` category (or the best match if no `family` row exists) with that category's `tone` and `constraints`, SHALL keep the raw best similarity as `confidence_score`, and SHALL set `is_fallback` to `true`.

#### Scenario: Weak match
- **WHEN** the best similarity is 0.22
- **THEN** `matched_category` is `"family"`, `confidence_score` is 0.22, and `is_fallback` is `true`

### Requirement: Empty reference data fallback
When `itinerary_categories` has no rows, or every row has a null embedding, the step SHALL report `matched_category` = `"family"`, `confidence_score` = 0.0, `tone` = `"friendly and helpful"`, `constraints` = `""`, and `is_fallback` = `true`.

#### Scenario: Categories table is empty
- **WHEN** `itinerary_categories` contains no rows
- **THEN** the cag_match event has `confidence_score` = 0.0 and `is_fallback` = `true`
- **AND** the step status is `"completed"`

### Requirement: CAG match event
The `cag_match` event `data` SHALL contain `matched_category`, `confidence_score`, `tone`, `constraints`, and `is_fallback`.

#### Scenario: Event payload
- **WHEN** `cag_match` completes
- **THEN** its event `data` has exactly those five keys

### Requirement: Retrieval routing threshold
The `retrieval_decision` condition SHALL compare the cag_match `confidence_score` with `RETRIEVAL_CONFIDENCE_THRESHOLD` (0.85). A score below the threshold SHALL route to `rag_retrieve`; a score at or above it SHALL skip retrieval and proceed to `generate`. A missing or unparseable score SHALL be treated as 0.0, which routes to retrieval.

#### Scenario: High confidence skips retrieval
- **WHEN** `confidence_score` is 0.85
- **THEN** `rag_retrieve` does not run

#### Scenario: Low confidence triggers retrieval
- **WHEN** `confidence_score` is 0.84
- **THEN** `rag_retrieve` runs

#### Scenario: Score unavailable
- **WHEN** the cag_match output is missing or malformed
- **THEN** the score is treated as 0.0 and `rag_retrieve` runs

### Requirement: Routing decision event
The `retrieval_decision` step SHALL emit an event on both branches whose `data` contains `routing_decision` (`"rag_retrieve"` or `"generate"`), `confidence_score`, and `threshold`. In the current implementation the event is written to stdout by the condition evaluator and collected by the API layer.

#### Scenario: Decision visible in stream
- **WHEN** retrieval is skipped
- **THEN** the stream still contains a `retrieval_decision` event with `routing_decision` = `"generate"`
