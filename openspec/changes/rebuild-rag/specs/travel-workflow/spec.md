## REMOVED Requirements

### Requirement: Step order
**Reason**: `rag_retrieve` no longer depends on intent confidence; it runs on every request.
**Migration**: See "Workflow step order" below. Clients that relied on `rag_retrieve` being absent for some requests must expect it on every request.

## MODIFIED Requirements

### Requirement: Generate endpoint
The system SHALL expose `POST /generate`, accepting a JSON body with the required fields `destination`, `trip_length`, `budget`, and `travel_style`, an optional free-text field `notes`, and an optional integer query parameter `template_version`. The system SHALL respond with `Content-Type: text/event-stream`.

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

#### Scenario: Request with notes
- **WHEN** a client posts a valid body that also contains `"notes": "kids love animals"`
- **THEN** the response status is 200 and the notes are available to the retrieval and generate steps

### Requirement: Intake normalisation
The intake step SHALL validate the request with the `TravelRequest` model and SHALL emit the normalised fields: `destination` stripped of surrounding whitespace and lowercased, `trip_length` as an integer of at least 1, `budget` as one of `budget` / `moderate` / `luxury`, `travel_style` stripped of surrounding whitespace but otherwise kept as free text, and `notes` stripped of surrounding whitespace, at most 500 characters, and `null` when absent or blank. Unknown extra fields SHALL be ignored.

#### Scenario: Destination is normalised
- **WHEN** the request has `destination` = `"  Sydney "`
- **THEN** the intake event `data.destination` is `"sydney"`

#### Scenario: Extra fields are ignored
- **WHEN** the request body contains an unrecognised field
- **THEN** the field is dropped and validation still succeeds

#### Scenario: Blank notes
- **WHEN** the request has `notes` = `"   "`
- **THEN** the intake event `data.notes` is `null`

#### Scenario: Notes too long
- **WHEN** the request has `notes` longer than 500 characters
- **THEN** the response status is 422

## ADDED Requirements

### Requirement: Workflow step order
The workflow SHALL execute its steps in this fixed order for every request: `intake`, `cag_match`, `retrieval_decision`, `rag_retrieve`, `generate`, `validate_output`.

#### Scenario: Any request
- **WHEN** a request is processed
- **THEN** the stream contains events for all six steps in that order
