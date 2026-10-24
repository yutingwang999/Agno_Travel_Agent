## REMOVED Requirements

### Requirement: Step order
**Reason**: The step `cag_match` is renamed `intent_match`, and the conditional branch now chooses between `cag_context` and `rag_retrieve` by knowledge mode rather than skipping retrieval by confidence.
**Migration**: See "Workflow step order" below. Clients matching on `step` = `"cag_match"` must use `"intent_match"`.

## MODIFIED Requirements

### Requirement: Incremental event delivery
`POST /generate` SHALL write each step's event to the SSE stream as soon as that step finishes, without waiting for later steps, and events SHALL arrive in the order the steps executed.

#### Scenario: First event arrives before generation finishes
- **WHEN** a request is processed and the generate step takes several seconds
- **THEN** the `intake` and `intent_match` events are received by the client before the `generate` step finishes

#### Scenario: Order preserved
- **WHEN** a request is processed in RAG mode
- **THEN** events arrive in the order `intake`, `intent_match`, `retrieval_decision`, `rag_retrieve`, `generate`, `validate_output`

### Requirement: Per-step trace record
Each executed step SHALL write one row to `trace_events` containing `session_id`, `step_name`, `status`, and `latency_ms`. The generate step SHALL also record `prompt_template_key` and `prompt_template_version` on success; the validate_output step SHALL also record `degraded_mode` and, when applicable, `error_type`. A failure to write a trace row SHALL be logged and SHALL NOT fail the step.

#### Scenario: Trace rows for a run
- **WHEN** a CAG-mode run completes
- **THEN** `trace_events` contains one row each for `intake`, `intent_match`, `retrieval_decision`, `cag_context`, `generate`, and `validate_output` with the request's `session_id`

#### Scenario: Trace database unavailable
- **WHEN** inserting the trace row raises a database error
- **THEN** the error is logged and the step still returns its event

## ADDED Requirements

### Requirement: Workflow step order
The workflow SHALL execute its steps in this fixed order: `intake`, `intent_match`, `retrieval_decision`, then exactly one of `cag_context` (knowledge mode `"cag"`) or `rag_retrieve` (knowledge mode `"rag"`), then `generate`, `validate_output`.

#### Scenario: CAG-mode run
- **WHEN** `retrieval_decision` chooses `"cag"`
- **THEN** the stream contains `intake`, `intent_match`, `retrieval_decision`, `cag_context`, `generate`, `validate_output` in that order, and no `rag_retrieve` event

#### Scenario: RAG-mode run
- **WHEN** `retrieval_decision` chooses `"rag"`
- **THEN** the stream contains `intake`, `intent_match`, `retrieval_decision`, `rag_retrieve`, `generate`, `validate_output` in that order, and no `cag_context` event
