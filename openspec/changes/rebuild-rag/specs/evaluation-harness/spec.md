## MODIFIED Requirements

### Requirement: Section-level relevance
A retrieved chunk SHALL count as relevant to an entry when the pair identifying it appears in that entry's `relevant_sections`, where the label field `source` holds the first element of the pair. A chunk from a corpus page SHALL be identified as (page title, `section`); a handwritten document, with or without a `section` field, SHALL be identified as `source` = `"handwritten"` and `section` = the document title. Relevance labels SHALL be tied to a recorded corpus version.

#### Scenario: v0.1.0 handwritten documents
- **WHEN** the retrieval step returns the document titled "Family Adventure Travel in Australia"
- **THEN** it is matched against labels as `("handwritten", "Family Adventure Travel in Australia")`

#### Scenario: Same section on two pages
- **WHEN** the retrieval step returns a chunk from section "Eat" of the page "Sydney/City Centre"
- **THEN** it is matched against labels as `("Sydney/City Centre", "Eat")` and does not match a label for section "Eat" of another page

## ADDED Requirements

### Requirement: Corpus coverage grouping
Plan entries of a corpus-versioned dataset SHALL carry `corpus_coverage`: `"city"` when their labels include corpus pages, `"national_only"` when they include only Australia-wide documents, `"none"` when they have no labels because the corpus holds nothing for the request. The dataset check SHALL reject a value that disagrees with the labels. An entry with `"none"` SHALL take no part in Recall and MRR, and the run summary SHALL report `supported_share` per group.

#### Scenario: Destination outside the corpus
- **WHEN** an entry requests a destination for which neither pages nor Australia-wide documents apply
- **THEN** it has `corpus_coverage` = `"none"` and empty `relevant_sections`, passes the dataset check, and is left out of Recall

#### Scenario: Faithfulness per group
- **WHEN** a run finishes on a dataset with `corpus_coverage`
- **THEN** its summary has `metrics.faithfulness.by_corpus_coverage` with `itineraries`, `claims` and `supported_share` per group

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
