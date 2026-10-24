# knowledge-retrieval Specification

## Purpose
Defines the RAG side of the workflow: the `rag_retrieve` step, which runs only on the low-confidence branch and retrieves the most relevant Australian travel document chunks from the Agno-managed knowledge base so the generate step can inject them into the prompt.

## Requirements

### Requirement: Conditional execution
The `rag_retrieve` step SHALL run only when `retrieval_decision` routes to retrieval (see `intent-routing`).

#### Scenario: Skipped on high confidence
- **WHEN** `retrieval_decision` routes to `generate`
- **THEN** no `rag_retrieve` event is emitted and no trace row is written for it

### Requirement: Retrieval query construction
The step SHALL build the query text by joining, with single spaces: the intake `travel_style` (if present); `"travel in {destination}"` using the intake destination, or `"travel in Australia"` when the destination is empty; and `"{matched_category} itinerary"` (if a category was matched).

#### Scenario: Full query
- **WHEN** intake has `travel_style` = `"family"`, `destination` = `"sydney"` and cag_match has `matched_category` = `"family"`
- **THEN** the query text is `"family travel in sydney family itinerary"`

#### Scenario: Missing destination
- **WHEN** the intake destination is empty and no other fields are available
- **THEN** the query text is `"travel in Australia"`

### Requirement: Knowledge base search
The step SHALL search an Agno `Knowledge` instance backed by `PgVector` on the `travel_docs` table in the `ai` schema, using vector search with cosine distance and the project's Gemini embedder with the same model and 768 dimensions used at seed time. It SHALL request at most 5 results (`top_k` = 5), ordered most relevant first.

#### Scenario: Top-k limit
- **WHEN** the knowledge base holds 13 documents
- **THEN** at most 5 chunks are returned

### Requirement: Retrieved chunk shape
Each retrieved chunk SHALL be reported as `{"destination", "title", "chunk_text"}`, where `destination` comes from the document metadata, `title` is the document name, and `chunk_text` is the document content.

#### Scenario: Chunk fields
- **WHEN** a document named "Family Adventure Travel in Australia" is retrieved
- **THEN** its chunk has `title` = `"Family Adventure Travel in Australia"` and non-empty `chunk_text`

### Requirement: Retrieval event
The `rag_retrieve` event `data` SHALL contain `retrieved_context` (the list of chunks), `chunks_retrieved` (the list length), and `query_text`.

#### Scenario: Event payload
- **WHEN** 5 chunks are retrieved
- **THEN** `chunks_retrieved` is 5 and `retrieved_context` has 5 entries

### Requirement: Graceful degradation
Any exception raised while building the knowledge base, embedding the query, or searching SHALL be logged, and the step SHALL still complete with `status` = `"completed"` and an empty `retrieved_context`. The workflow SHALL continue to the generate step.

#### Scenario: Vector search fails
- **WHEN** the embedding call or vector query raises
- **THEN** the event has `status` = `"completed"`, `retrieved_context` = `[]`, and `chunks_retrieved` = 0
- **AND** the generate step still runs

### Requirement: Knowledge base seeding
`scripts/seed.py` SHALL populate the knowledge base by inserting each source document through `Knowledge.insert()` with `skip_if_exists=True`, storing `destination` and the document's category tags in the document metadata. If `ai.travel_docs` exists without an `embedding` column, the seed SHALL drop and recreate it before inserting.

#### Scenario: Re-running seed
- **WHEN** the seed script is run twice
- **THEN** no duplicate documents are created
