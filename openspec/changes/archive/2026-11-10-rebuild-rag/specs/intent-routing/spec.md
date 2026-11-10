## REMOVED Requirements

### Requirement: Retrieval routing threshold
**Reason**: Skipping retrieval when intent confidence is high left the most clearly specified requests with no destination knowledge at all (the high-confidence template has no knowledge placeholder), so retrieval improvements could not reach them. Confidence measures similarity to an itinerary category, not whether knowledge is needed.
**Migration**: See "Interim retrieval routing" below. A redesigned routing rule is roadmap item 3.

## MODIFIED Requirements

### Requirement: Routing decision event
The `retrieval_decision` step SHALL emit an event whose `data` contains `routing_decision` (always `"rag_retrieve"` under the interim routing rule) and `confidence_score` (reported for information only). The event SHALL be delivered through the same step-output channel as every other step's event, and SHALL NOT be written to or read from standard output.

#### Scenario: Decision visible in stream
- **WHEN** a request is processed
- **THEN** the stream contains a `retrieval_decision` event with `routing_decision` = `"rag_retrieve"`

#### Scenario: No stdout side effect
- **WHEN** the routing decision is made
- **THEN** nothing is printed to standard output by the workflow

## ADDED Requirements

### Requirement: Interim retrieval routing
The `retrieval_decision` step SHALL route every request to `rag_retrieve`, regardless of the intent confidence score.

#### Scenario: High confidence still retrieves
- **WHEN** `confidence_score` is 0.95
- **THEN** `rag_retrieve` runs
