## MODIFIED Requirements

### Requirement: Slot extraction metric
When the evaluated configuration includes a request parser, the harness SHALL report slot extraction accuracy per slot (destination, trip length, budget, preferences) against `gold_slots`, over entries whose `expected_behavior` is `plan`; otherwise it SHALL report the metric as not applicable with the reason. Destination, trip length and budget level SHALL be compared exactly, where a gold `budget` of null means the utterance states no budget and is matched only when the parser left the budget unstated, before any default. Preferences SHALL be reported as recall: a gold preference is covered when a parsed preference or the parsed travel style contains it, case-insensitively.

#### Scenario: No parser in the configuration
- **WHEN** the v0.1.0 configuration is evaluated
- **THEN** slot extraction accuracy is reported as N/A, "no request parser"

#### Scenario: Non-plan entries excluded
- **WHEN** a configuration with a request parser is evaluated and an entry expects `refuse`
- **THEN** that entry's slots are not counted in slot extraction accuracy

#### Scenario: Unstated budget
- **WHEN** an entry's gold `budget` is null and the parser leaves the budget unstated, so the default `moderate` is applied
- **THEN** the budget slot counts as correct for that entry

#### Scenario: Preference covered by the travel style
- **WHEN** the gold preferences are `["family", "kids"]` and the parsed travel style is `"family with young kids"` with no parsed preferences
- **THEN** both gold preferences count as covered

### Requirement: Behaviour correctness metric
The harness SHALL classify each request's observed behaviour as `plan` (a validated itinerary), `refuse` (a 422 response carrying a guard reason code), `clarify` (on the free-text path, a parse that leaves `destination` or `trip_length` for the user to fill in), `invalid_input` (a 422 response without a guard reason code), or `error` (an error event, an unhandled exception, or an aborted stream), and SHALL report the share of entries whose behaviour matches `expected_behavior`, overall and per tag. An exception SHALL be recorded for that entry and SHALL NOT stop the run.

#### Scenario: Out-of-scope request planned anyway
- **WHEN** an entry tagged `out_of_scope` with `expected_behavior` = `refuse` produces an itinerary
- **THEN** it counts as incorrect behaviour

#### Scenario: Workflow raises
- **WHEN** the workflow raises an exception for one entry
- **THEN** that entry is recorded as `error` and the remaining entries are still evaluated

#### Scenario: Parse leaves the destination empty
- **WHEN** on the free-text path the parse of an entry's utterance lists `destination` in `missing`
- **THEN** the entry's observed behaviour is `clarify` and no itinerary is requested

### Requirement: Clarify expectations
An entry whose `expected_behavior` is `clarify` SHALL count as correct only when its observed behaviour is `clarify`. On the form path, and on the free-text path whenever the parse is complete, no clarifying question is observed, so such an entry SHALL count as incorrect until a later change observes clarifying questions for contradictory requests.

#### Scenario: Clarify entry
- **WHEN** an entry with `expected_behavior` = `clarify` produces an itinerary
- **THEN** it counts as incorrect behaviour

#### Scenario: Underspecified entry on the free-text path
- **WHEN** an entry with `expected_behavior` = `clarify` has an utterance without a destination and its parse lists `destination` in `missing`
- **THEN** it counts as correct behaviour

## ADDED Requirements

### Requirement: Free-text path evaluation
A configuration with `request_parser` = true SHALL evaluate each entry by sending its `utterance` to `POST /parse` and, when the parse is complete, sending the parsed request to `POST /generate` with the configuration's template version, without simulating any edit by the user. The judges SHALL receive the entry's `form` fields (`destination`, `travel_style`, `notes`) on both paths, so both paths are judged against what the traveller asked.

#### Scenario: Complete parse
- **WHEN** an entry's utterance parses with every required field
- **THEN** the parsed request is sent to `/generate` and the itinerary is judged against the entry's `form`

#### Scenario: Parse rejected
- **WHEN** `/parse` rejects an entry's utterance with a guard reason code
- **THEN** the entry's observed behaviour is `refuse` and `/generate` is not called

### Requirement: Parsed field agreement
For a parser configuration, the harness SHALL report, over `plan` entries, the share of parses whose `destination`, `trip_length`, `budget` (after defaults) and `max_daily_budget_aud` each equal the entry's `form`, and the share whose `notes` agree on presence (both empty or both non-empty).

#### Scenario: Notes presence
- **WHEN** an entry's `form` has notes and its parse has empty notes
- **THEN** that entry counts against notes agreement

### Requirement: Parser latency and cost
For a parser configuration, the harness SHALL report the p50 and p95 latency of `/parse` and its mean cost per request from its trace row's token usage, separately, and SHALL include the parse cost in the mean cost per request.

#### Scenario: Cost with parsing
- **WHEN** a free-text run completes
- **THEN** the report shows parse latency and parse cost, and the per-request cost includes the parse

### Requirement: Parse-only runs
`scripts/eval_run.py` SHALL offer a parse-only mode that sends only `/parse` for each entry and reports slot extraction accuracy, parsed field agreement, the observed parse behaviour (`refuse`, `clarify`, or complete), and parser latency and cost, without generating or judging.

#### Scenario: Iterating on the parser prompt
- **WHEN** a parse-only run is made
- **THEN** no `/generate` call or judge call is made and the summary holds the parser metrics
