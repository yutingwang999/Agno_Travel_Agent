## REMOVED Requirements

### Requirement: Conditional execution
**Reason**: Retrieval now runs on every request (see `intent-routing` — "Interim retrieval routing").
**Migration**: See "Retrieval on every request" below.

## MODIFIED Requirements

### Requirement: Retrieval query construction
The step SHALL build the query text by joining, with single spaces: the request `notes` (if present); the intake `travel_style` (if present); `"travel in {destination}"` using the intake destination, or `"travel in Australia"` when the destination is empty; and `"{matched_category} itinerary"` (if a category was matched).

#### Scenario: Full query
- **WHEN** intake has `travel_style` = `"family"`, `destination` = `"sydney"` and cag_match has `matched_category` = `"family"`
- **THEN** the query text is `"family travel in sydney family itinerary"`

#### Scenario: Missing destination
- **WHEN** the intake destination is empty and no other fields are available
- **THEN** the query text is `"travel in Australia"`

#### Scenario: Notes included
- **WHEN** the request has `notes` = `"kids love animals"`, `travel_style` = `"family"`, `destination` = `"sydney"`, and `matched_category` = `"family"`
- **THEN** the query text is `"kids love animals family travel in sydney family itinerary"`

### Requirement: Knowledge base search
The step SHALL rank the destination-filtered chunks of the knowledge base by relevance to the query text and SHALL return at most 5 chunks (`top_k` = 5), most relevant first. The ranking method (search modes, fusion, and reranking) SHALL be the configuration selected by the stepwise retrieval comparison and recorded, with its evaluation results, in `docs/experiments.md`.

#### Scenario: Top-k limit
- **WHEN** more than 5 chunks pass the destination filter
- **THEN** exactly 5 chunks are returned, most relevant first

#### Scenario: Selected configuration recorded
- **WHEN** the change is ready to archive
- **THEN** `docs/experiments.md` names the ranking configuration in use and shows its Recall@5 and MRR@5 against the vector-only baseline

### Requirement: Retrieved chunk shape
Each retrieved chunk SHALL be reported as `{"chunk_id", "destination", "state", "title", "chunk_text", "source", "section"}`, where `chunk_id` is a stable identifier, `destination` is the lowercase city from the chunk metadata (or `"australia"`), `state` is the Australian state or territory (or null for national documents), `title` is the document name, `chunk_text` is the chunk content, `source` is the source URL (or `"handwritten"`), and `section` is the heading of the section the chunk came from.

#### Scenario: Chunk fields
- **WHEN** a chunk from the Wikivoyage "Sydney" page, section "Eat", is retrieved
- **THEN** it has `destination` = `"sydney"`, `state` = `"New South Wales"`, a `source` URL, and `section` = `"Eat"`

### Requirement: Knowledge base seeding
`scripts/seed.py` SHALL load the chunked corpus from `data/knowledge/`, SHALL insert every chunk into the configured knowledge base table with `chunk_id`, `destination` (lowercase), `state`, `topic`, `source`, and `section` metadata, and SHALL be idempotent. When the chunking configuration changes, re-running the seed into the same table SHALL rebuild it so that no chunks from the previous configuration remain.

#### Scenario: Re-running seed
- **WHEN** the seed script is run twice with the same configuration
- **THEN** no duplicate chunks are created

#### Scenario: Chunking configuration changed
- **WHEN** the chunk size is changed and the seed is run again into the same table
- **THEN** that table contains only chunks produced with the new chunk size

## ADDED Requirements

### Requirement: Retrieval on every request
The `rag_retrieve` step SHALL run for every request that reaches the workflow.

#### Scenario: High-confidence request
- **WHEN** a request has intent confidence 0.95
- **THEN** the stream contains a `rag_retrieve` event

### Requirement: Corpus build pipeline
`scripts/build_corpus.py` SHALL turn the downloaded openly licensed sources into the chunked corpus in `data/knowledge/` by cleaning the text, splitting it along the sources' section structure (further splitting overly long sections), and attaching the chunk metadata; every source SHALL have its licence recorded, and re-running the pipeline on the same inputs SHALL produce identical output.

#### Scenario: Deterministic rebuild
- **WHEN** the pipeline is run twice on the same downloaded sources and configuration
- **THEN** the two outputs contain the same chunks with the same `chunk_id` values

#### Scenario: Licence recorded
- **WHEN** a new source is added to the corpus
- **THEN** its licence and attribution are listed in `data/knowledge/LICENSE.md`

### Requirement: Destination filtering
Before ranking, the step SHALL restrict candidates to chunks whose `destination` equals the request destination or `"australia"`. If the knowledge base has no chunks for the request destination, the step SHALL search only `"australia"` chunks. The event `data` SHALL include `destination_matched`, true when chunks exist for the request destination.

#### Scenario: Known city
- **WHEN** the request destination is `"sydney"`
- **THEN** every returned chunk has `destination` = `"sydney"` or `"australia"`
- **AND** `destination_matched` is `true`

#### Scenario: City not in the knowledge base
- **WHEN** the request destination is `"darwin"` and no chunk has `destination` = `"darwin"`
- **THEN** every returned chunk has `destination` = `"australia"`
- **AND** `destination_matched` is `false`

### Requirement: Reranking failure fallback
If the selected ranking configuration uses a reranker and the reranker fails to load or raises during scoring, the step SHALL log the error and SHALL return the top 5 chunks in the order produced before reranking, still completing with `status` = `"completed"`.

#### Scenario: Reranker unavailable
- **WHEN** the configuration uses a reranker and the reranking model cannot be loaded
- **THEN** the step returns up to 5 chunks in pre-reranking order and the workflow continues
