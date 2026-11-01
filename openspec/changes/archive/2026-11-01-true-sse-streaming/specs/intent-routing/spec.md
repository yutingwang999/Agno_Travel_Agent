## MODIFIED Requirements

### Requirement: Routing decision event
The `retrieval_decision` step SHALL emit an event on both branches whose `data` contains `routing_decision` (`"rag_retrieve"` or `"generate"`), `confidence_score`, and `threshold`. The event SHALL be delivered through the same step-output channel as every other step's event, and SHALL NOT be written to or read from standard output.

#### Scenario: Decision visible in stream
- **WHEN** retrieval is skipped
- **THEN** the stream still contains a `retrieval_decision` event with `routing_decision` = `"generate"`

#### Scenario: No stdout side effect
- **WHEN** the routing decision is made
- **THEN** nothing is printed to standard output by the workflow
