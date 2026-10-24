## MODIFIED Requirements

### Requirement: Output schema
A valid itinerary SHALL conform to `ItineraryOutput`: `destination` (string), `trip_length_days` (integer), `budget_level` (string), `travel_style` (string), `daily_itinerary` (list of items with `day` integer, `morning` / `afternoon` / `evening` strings, `estimated_cost_aud` number, and `sources` list of citation id strings), `total_estimated_cost_aud` (number), and `key_tips` (list of strings).

#### Scenario: Missing field
- **WHEN** the parsed JSON has no `key_tips`
- **THEN** validation fails with the Pydantic error message

#### Scenario: Day without sources
- **WHEN** a daily item has `sources` = `[]`
- **THEN** schema validation passes for that item

## ADDED Requirements

### Requirement: Citation validity
After schema validation passes, every citation id in any `daily_itinerary[].sources` SHALL be one of the ids in the generate event's `context_sources`; when `context_sources` is empty, every `sources` list SHALL be empty. A violation SHALL fail validation with a message beginning `"Business rule failed: citation"`, triggering the existing corrective retry.

#### Scenario: Invented citation
- **WHEN** a day cites `S7` but `context_sources` only has `S1` to `S5`
- **THEN** validation fails with a message beginning `"Business rule failed: citation"`

#### Scenario: Citation without context
- **WHEN** no knowledge context was provided and a day cites `S1`
- **THEN** validation fails with a message beginning `"Business rule failed: citation"`

### Requirement: Citation details in output event
When validation succeeds, the validate_output event `data` SHALL include `citations`, mapping every citation id used in the itinerary to its `{"title", "source", "section"}` from `context_sources`, so the frontend can display the sources for each day.

#### Scenario: Citations resolved
- **WHEN** a valid itinerary cites `S1` and `S3`
- **THEN** `data.citations` has entries for `S1` and `S3` with their titles and source URLs
