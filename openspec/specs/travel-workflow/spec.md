# travel-workflow Specification

## Purpose
Defines how a travel planning request enters the system through `POST /generate`, how it is validated and normalised (intake), how the six Agno workflow steps are ordered and hand data to one another, the structured SSE event contract every step emits, and the per-step trace record each step writes. Step-specific behaviour is specified in `intent-routing`, `knowledge-retrieval`, `itinerary-generation`, and `output-validation`.

## Requirements

### Requirement: Generate endpoint
The system SHALL expose `POST /generate`, accepting a JSON body with the required fields `destination`, `trip_length`, `budget`, and `travel_style`, and an optional integer query parameter `template_version`. The system SHALL respond with `Content-Type: text/event-stream`.

#### Scenario: Valid request
- **WHEN** a client posts `{"destination": "Sydney", "trip_length": 5, "budget": "moderate", "travel_style": "family"}`
- **THEN** the response status is 200
- **AND** the body is an SSE stream whose `data` lines are JSON step events

#### Scenario: Invalid request body
- **WHEN** a required field is missing, `trip_length` is less than 1, `budget` is not one of `budget`, `moderate`, `luxury`, or `destination` / `travel_style` is blank
- **THEN** the response status is 422
- **AND** the workflow is not executed

#### Scenario: Template version override is forwarded
- **WHEN** a client posts to `/generate?template_version=2`
- **THEN** the value `2` is passed to the workflow as `template_version` and used by the generate step

### Requirement: Session identifier
The system SHALL generate a new UUID4 `session_id` for every `POST /generate` request and SHALL propagate it to every workflow step, so that every SSE event and trace row produced by that request carries the same `session_id`.

#### Scenario: Shared session id
- **WHEN** a single request produces events for several steps
- **THEN** every event in the stream has the same `session_id`
- **AND** that `session_id` differs from the one produced by any other request

### Requirement: Intake normalisation
The intake step SHALL validate the request with the `TravelRequest` model and SHALL emit the normalised fields: `destination` stripped of surrounding whitespace and lowercased, `trip_length` as an integer of at least 1, `budget` as one of `budget` / `moderate` / `luxury`, and `travel_style` stripped of surrounding whitespace but otherwise kept as free text. Unknown extra fields SHALL be ignored.

#### Scenario: Destination is normalised
- **WHEN** the request has `destination` = `"  Sydney "`
- **THEN** the intake event `data.destination` is `"sydney"`

#### Scenario: Extra fields are ignored
- **WHEN** the request body contains an unrecognised field
- **THEN** the field is dropped and validation still succeeds

### Requirement: Step order
The workflow SHALL execute its steps in this fixed order: `intake`, `cag_match`, `retrieval_decision`, `rag_retrieve` (only when `retrieval_decision` routes to retrieval), `generate`, `validate_output`.

#### Scenario: High-confidence run
- **WHEN** `retrieval_decision` routes to `generate`
- **THEN** the stream contains events for `intake`, `cag_match`, `retrieval_decision`, `generate`, `validate_output` in that order
- **AND** no `rag_retrieve` event is present

#### Scenario: Low-confidence run
- **WHEN** `retrieval_decision` routes to `rag_retrieve`
- **THEN** the stream contains events for all six steps in the order above

### Requirement: SSE event envelope
Every step SHALL emit exactly one event shaped as `{"session_id", "step", "status", "timestamp", "data", "error"}`, where `status` is `"completed"` or `"error"`, `timestamp` is an ISO-8601 UTC string, `data` is an object (empty when there is nothing to report), and `error` is `null` unless the step failed.

#### Scenario: Completed step
- **WHEN** a step finishes successfully
- **THEN** its event has `status` = `"completed"` and `error` = `null`

#### Scenario: Failed step
- **WHEN** a step reports a handled failure
- **THEN** its event has `status` = `"error"` and `error` contains a human-readable message

### Requirement: Inter-step data handoff
Each step SHALL return its SSE event, serialised as JSON, as its step output content. Downstream steps SHALL read upstream values from those serialised events (or from the request fields passed as workflow `additional_data`). A missing or malformed upstream event SHALL be treated as an empty value rather than raising.

#### Scenario: Upstream output missing
- **WHEN** a step reads a field from an upstream step that did not run
- **THEN** it receives an empty value and continues

### Requirement: Event delivery timing
In the current implementation, `POST /generate` SHALL run the whole workflow to completion, collect all step events, sort them into the canonical step order, and only then write them to the SSE stream.

#### Scenario: Events arrive together
- **WHEN** a request is processed
- **THEN** no event is sent until the `validate_output` step has finished
- **AND** all events are then sent in canonical order

### Requirement: Per-step trace record
Each executed step SHALL write one row to `trace_events` containing `session_id`, `step_name`, `status`, and `latency_ms`. The generate step SHALL also record `prompt_template_key` and `prompt_template_version` on success; the validate_output step SHALL also record `degraded_mode` and, when applicable, `error_type`. A failure to write a trace row SHALL be logged and SHALL NOT fail the step.

#### Scenario: Trace rows for a run
- **WHEN** a high-confidence run completes
- **THEN** `trace_events` contains one row each for `intake`, `cag_match`, `retrieval_decision`, `generate`, and `validate_output` with the request's `session_id`

#### Scenario: Trace database unavailable
- **WHEN** inserting the trace row raises a database error
- **THEN** the error is logged and the step still returns its event
