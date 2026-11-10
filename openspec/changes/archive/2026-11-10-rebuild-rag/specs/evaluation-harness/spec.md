## MODIFIED Requirements

### Requirement: Section-level relevance
A retrieved chunk SHALL count as relevant to an entry when the pair identifying it appears in that entry's `relevant_sections`, where the label field `source` holds the first element of the pair. A chunk from a corpus page SHALL be identified as (page title, `section`); a handwritten document, with or without a `section` field, SHALL be identified as `source` = `"handwritten"` and `section` = the document title. Relevance labels SHALL be tied to a recorded corpus version.

#### Scenario: v0.1.0 handwritten documents
- **WHEN** the retrieval step returns the document titled "Family Adventure Travel in Australia"
- **THEN** it is matched against labels as `("handwritten", "Family Adventure Travel in Australia")`

#### Scenario: Same section on two pages
- **WHEN** the retrieval step returns a chunk from section "Eat" of the page "Sydney/City Centre"
- **THEN** it is matched against labels as `("Sydney/City Centre", "Eat")` and does not match a label for section "Eat" of another page

### Requirement: Faithfulness metric
For each generated itinerary, a judge model configured separately from the generation model SHALL extract the specific claims in these categories — opening hours, prices, named venues or attractions, transport modes or durations, specific activities at a specific place, and seasons — and decide for each whether it is supported by the knowledge context given to the generator. The harness SHALL report the share of supported claims overall and separately for requests generated with and without knowledge context.

#### Scenario: Unsupported claim
- **WHEN** the itinerary states an opening time that does not appear in the knowledge context
- **THEN** that claim is counted as unsupported

#### Scenario: General description is not a claim
- **WHEN** the itinerary says "enjoy the harbour views"
- **THEN** no claim is extracted from that phrase

#### Scenario: Activity at another place
- **WHEN** the itinerary says "swim with seals at Dunmore Beach" and the knowledge context offers that activity only at another place
- **THEN** the activity is counted as unsupported

#### Scenario: Season with different months
- **WHEN** the itinerary gives June to August as the best time for a place and the knowledge context gives November to February
- **THEN** the season is counted as unsupported

## ADDED Requirements

### Requirement: Destination check honours notes
The judge deciding whether the places in an itinerary are in the destination SHALL also receive the request's `notes`, and a place the traveller explicitly asked for in them SHALL count as in scope.

#### Scenario: Stop asked for in the notes
- **WHEN** the notes say "Include Kangaroo Island" for a trip to Adelaide and the itinerary goes there
- **THEN** that place counts as in the destination

### Requirement: Preference adherence metric
The judge SHALL receive the request's `travel_style` and `notes` and the itinerary, and SHALL list each stated preference with whether the itinerary follows it, and each requirement the itinerary adds that the traveller did not state. The harness SHALL report the share of preferences followed and the number of added requirements, which SHALL NOT count as failures. Calibration samples SHALL include these verdicts.

#### Scenario: Ignored preference
- **WHEN** the travel style is "surfing" and the itinerary has no surfing
- **THEN** that preference counts as not followed

#### Scenario: Added requirement
- **WHEN** the travel style is "seniors, slow pace" and the itinerary restricts every venue to wheelchair access
- **THEN** that requirement is listed and counted, and the followed share is unaffected

### Requirement: Re-judging a stored run
The harness SHALL be able to apply the current judge prompts to a stored run without regenerating its itineraries, writing a new run that names its source and the prompt versions used.

#### Scenario: Before and after on the same prompt
- **WHEN** a stored run is re-judged
- **THEN** the new run's itineraries and knowledge context are those of the source, and its summary names the source run and the judge prompt versions

### Requirement: Corpus coverage grouping
Plan entries of a corpus-versioned dataset SHALL carry `corpus_coverage`: `"city"` when their labels include corpus pages, `"national_only"` when they include only Australia-wide documents, `"none"` when they have no labels because the corpus holds nothing for the request. The dataset check SHALL reject a value that disagrees with the labels. An entry with `"none"` SHALL take no part in Recall and MRR, and the run summary SHALL report `supported_share` per group.

#### Scenario: Destination outside the corpus
- **WHEN** an entry requests a destination for which neither pages nor Australia-wide documents apply
- **THEN** it has `corpus_coverage` = `"none"` and empty `relevant_sections`, passes the dataset check, and is left out of Recall

#### Scenario: Faithfulness per group
- **WHEN** a run finishes on a dataset with `corpus_coverage`
- **THEN** its summary has `metrics.faithfulness.by_corpus_coverage` with `itineraries`, `claims` and `supported_share` per group

### Requirement: Stepwise retrieval comparison
These retrieval configurations SHALL have been evaluated on the same corpus version, each adding one change to the previous: (a) vector-only, (b) vector with destination filtering, (c) hybrid lexical and vector search with fusion and destination filtering, (d) configuration (c) with reranking; and the comparison report SHALL list Recall@5, MRR@5, and retrieval latency p50/p95 for each.

#### Scenario: All four steps reported
- **WHEN** the stepwise comparison is run on corpus version v2
- **THEN** `docs/experiments.md` has one row for each of configurations (a) to (d), all on corpus version v2

### Requirement: Configurations not adopted
The harness SHALL keep supporting configurations (a) and (b). A configuration that was not adopted MAY be removed if `docs/experiments.md` names the commit that can re-run it.

#### Scenario: Removed configuration
- **WHEN** the code for configuration (d) is removed after it was not adopted
- **THEN** `docs/experiments.md` keeps its results and names a commit that still has that code

### Requirement: Citation accuracy metric
For itineraries that contain citations, the judge model SHALL decide whether each cited chunk supports the content of the day that cites it, and the harness SHALL report the share of supported citations and the share of days that have at least one citation when knowledge context was provided.

#### Scenario: Citation does not support the day
- **WHEN** a day about a harbour cruise cites a chunk about museum exhibitions
- **THEN** that citation is counted as unsupported
