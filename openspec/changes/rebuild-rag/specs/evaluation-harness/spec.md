## ADDED Requirements

### Requirement: Stepwise retrieval comparison
The harness SHALL support evaluating these retrieval configurations on the same corpus version, each adding one change to the previous: (a) vector-only, (b) vector with destination filtering, (c) hybrid lexical and vector search with fusion and destination filtering, (d) configuration (c) with reranking; and the comparison report SHALL list Recall@5, MRR@5, and retrieval latency p50/p95 for each.

#### Scenario: All four steps reported
- **WHEN** the stepwise comparison is run on corpus version v2
- **THEN** `docs/experiments.md` has one row for each of configurations (a) to (d), all on corpus version v2

### Requirement: Citation accuracy metric
For itineraries that contain citations, the judge model SHALL decide whether each cited chunk supports the content of the day that cites it, and the harness SHALL report the share of supported citations and the share of days that have at least one citation when knowledge context was provided.

#### Scenario: Citation does not support the day
- **WHEN** a day about a harbour cruise cites a chunk about museum exhibitions
- **THEN** that citation is counted as unsupported
