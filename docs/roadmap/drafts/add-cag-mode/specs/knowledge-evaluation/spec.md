## ADDED Requirements

### Requirement: Generation-level evaluation
`scripts/eval_generation.py` SHALL run the full workflow for every query in the evaluation dataset under a given knowledge configuration, and SHALL score each generated itinerary with a judge model for (a) the fraction of the query's `expected_facts` it covers and (b) the number of claims not supported by the knowledge context it was given. The judge model SHALL be configured separately from the generation model.

#### Scenario: Fact coverage scored
- **WHEN** a query has 4 expected facts and the itinerary covers 3
- **THEN** that query's fact coverage is 0.75

### Requirement: Knowledge mode comparison
The generation-level report SHALL compare, on the same corpus and dataset, at least: forced RAG with vector-only retrieval, forced RAG with the final hybrid retrieval, forced CAG, and the token-budget router; reporting mean fact coverage, unsupported-claim rate, latency p50/p95, and mean input tokens per request, written to `docs/experiments.md`.

#### Scenario: All arms reported
- **WHEN** the comparison is run
- **THEN** the report contains one row for each of the four configurations

### Requirement: Judge agreement check
The report SHALL include the agreement rate between the judge model and manual labels on a sample of at least 20 generated itineraries.

#### Scenario: Agreement reported
- **WHEN** the generation report is produced
- **THEN** it states the sample size and the judge–human agreement rate

### Requirement: Token budget calibration
The evaluation SHALL sweep at least four `KNOWLEDGE_TOKEN_BUDGET` values and report fact coverage, unsupported-claim rate, latency, and input tokens for each, so that the chosen default can be justified.

#### Scenario: Budget sweep
- **WHEN** the calibration is run with budgets 8k, 16k, 32k, and 64k
- **THEN** the report has one row per budget
