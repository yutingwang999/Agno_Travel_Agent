## REMOVED Requirements

### Requirement: Event delivery timing
**Reason**: Events were only sent after the whole workflow finished, so the stream was not incremental; replaced by "Incremental event delivery".
**Migration**: Clients need no change — the event format and order are unchanged; events now arrive as each step finishes.

## ADDED Requirements

### Requirement: Incremental event delivery
`POST /generate` SHALL write each step's event to the SSE stream as soon as that step finishes, without waiting for later steps, and events SHALL arrive in the order the steps executed.

#### Scenario: First event arrives before generation finishes
- **WHEN** a request is processed and the generate step takes several seconds
- **THEN** the `intake` and `cag_match` events are received by the client before the `generate` step finishes

#### Scenario: Order preserved
- **WHEN** a low-confidence request is processed
- **THEN** events arrive in the order `intake`, `cag_match`, `retrieval_decision`, `rag_retrieve`, `generate`, `validate_output`

### Requirement: Non-blocking request handling
While a workflow is running for one request, the service SHALL continue to accept and answer other HTTP requests; workflow execution SHALL NOT block the server's event loop, and concurrent requests SHALL NOT share mutable per-request state such as redirected standard output.

#### Scenario: Health check during generation
- **WHEN** a `POST /generate` request is in its generate step
- **THEN** a concurrent `GET /health` returns 200 without waiting for the generation to finish

#### Scenario: Concurrent requests keep their own events
- **WHEN** two `POST /generate` requests run at the same time
- **THEN** each stream contains only events carrying its own `session_id`
