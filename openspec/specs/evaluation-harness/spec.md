# evaluation-harness Specification

## Purpose
Defines how the quality, behaviour, and cost of the travel planner are measured: the labelled evaluation dataset, the evaluation environment, the metrics for each pipeline stage, how runs are executed and compared, and the regression gate, so that every change can be judged by reproducible numbers.

## Requirements

### Requirement: Evaluation dataset
The project SHALL keep a versioned evaluation dataset at `eval/dataset.jsonl` with 50 to 100 entries. Each entry SHALL contain `id`, `tags`, `form` (the structured request fields), `utterance` (a free-text phrasing of the same request), `gold_slots`, `expected_behavior` (`plan`, `refuse`, or `clarify`), `relevant_sections` (a list of `{source, section}` pairs). An entry MAY contain `expected_facts`; no metric requires it.

#### Scenario: Required fields present
- **WHEN** the dataset is loaded
- **THEN** every entry has all the required fields and a valid `expected_behavior`

#### Scenario: expected_facts omitted
- **WHEN** an entry has no `expected_facts`
- **THEN** the dataset still loads and the entry is evaluated

### Requirement: Request notes in the dataset
An entry's `form` MAY contain `notes`, free text of at most 500 characters holding request details the other form fields cannot express. The harness SHALL send `notes` with the request; a system without a `notes` field ignores it.

#### Scenario: Notes sent to v0.1.0
- **WHEN** an entry with `form.notes` is evaluated on the v0.1.0 configuration
- **THEN** the request carries `notes` and is processed as if it had none

### Requirement: Dataset coverage
The dataset SHALL cover several destinations, all three budget levels, a range of trip lengths, and several travel styles, and SHALL include entries tagged `contradictory`, `out_of_scope` (including at least one non-Australian destination), `prompt_injection`, `mixed_language` (Chinese and English mixed in the `utterance`), and `chinese_destination`.

#### Scenario: Coverage check
- **WHEN** the coverage check runs over the dataset
- **THEN** each required tag and each budget level appears at least once

### Requirement: Tag labelling rules
The `form.destination` of a `mixed_language` entry SHALL be an English place name; the `form.destination` of a `chinese_destination` entry SHALL be an Australian place name written in Chinese characters; every entry tagged `prompt_injection` SHALL have `expected_behavior` = `refuse`.

#### Scenario: Mixed-language form stays in English
- **WHEN** an entry is tagged `mixed_language`
- **THEN** its `form.destination` contains only an English place name

#### Scenario: Chinese destination in the form
- **WHEN** an entry is tagged `chinese_destination`
- **THEN** its `form.destination` is written in Chinese characters (e.g. `"悉尼"`)

#### Scenario: Prompt injection expects a refusal
- **WHEN** an entry is tagged `prompt_injection`
- **THEN** the coverage check fails unless its `expected_behavior` is `refuse`

### Requirement: Evaluation environment
Evaluation runs SHALL use a dedicated database named by `EVAL_DATABASE_URL`, separate from both the development and the test database. The knowledge base table used by a run SHALL be named per corpus version (for example `travel_docs_v1`) and selected by the run configuration, so that runs on earlier corpus versions remain reproducible after the corpus changes. Evaluation runs SHALL NOT send Agno telemetry.

#### Scenario: Re-running an old baseline
- **WHEN** corpus v2 has been built and the v0.1.0 baseline configuration is run again
- **THEN** the run uses `travel_docs_v1` and does not read v2 chunks

#### Scenario: Development data untouched
- **WHEN** a full evaluation run completes
- **THEN** no rows were written to the development database

#### Scenario: No telemetry during a run
- **WHEN** an evaluation run starts and `AGNO_TELEMETRY` is not set in the environment
- **THEN** the run sets it to `false` before the application is imported

### Requirement: Section-level relevance
A retrieved chunk SHALL count as relevant to an entry when the pair identifying it appears in that entry's `relevant_sections`, where the label field `source` holds the first element of the pair. A chunk from a corpus page SHALL be identified as (page title, `section`); a handwritten document, with or without a `section` field, SHALL be identified as `source` = `"handwritten"` and `section` = the document title. Relevance labels SHALL be tied to a recorded corpus version.

#### Scenario: v0.1.0 handwritten documents
- **WHEN** the retrieval step returns the document titled "Family Adventure Travel in Australia"
- **THEN** it is matched against labels as `("handwritten", "Family Adventure Travel in Australia")`

#### Scenario: Same section on two pages
- **WHEN** the retrieval step returns a chunk from section "Eat" of the page "Sydney/City Centre"
- **THEN** it is matched against labels as `("Sydney/City Centre", "Eat")` and does not match a label for section "Eat" of another page

### Requirement: Slot extraction metric
When the evaluated configuration includes a request parser, the harness SHALL report slot extraction accuracy per slot (destination, trip length, budget, preferences) against `gold_slots`, over entries whose `expected_behavior` is `plan`; otherwise it SHALL report the metric as not applicable with the reason.

#### Scenario: No parser in the configuration
- **WHEN** the v0.1.0 configuration is evaluated
- **THEN** slot extraction accuracy is reported as N/A, "no request parser"

#### Scenario: Non-plan entries excluded
- **WHEN** a configuration with a request parser is evaluated and an entry expects `refuse`
- **THEN** that entry's slots are not counted in slot extraction accuracy

### Requirement: Retrieval metrics
For every entry with non-empty `relevant_sections`, the harness SHALL run the intake and intent matching steps for that entry, build the retrieval query exactly as the workflow does, call the retrieval component directly, and report Recall@k and MRR@k (default k = 5), independent of whether the workflow would have routed the request to retrieval.

#### Scenario: Retrieval measured regardless of routing
- **WHEN** an entry would take the high-confidence path in the workflow
- **THEN** its retrieval metrics are still computed, using the same query text the workflow would build

### Requirement: Behaviour correctness metric
The harness SHALL classify each request's observed behaviour as `plan` (a validated itinerary), `refuse` (a 422 response carrying a guard reason code), `invalid_input` (a 422 response without a guard reason code), or `error` (an error event, an unhandled exception, or an aborted stream), and SHALL report the share of entries whose behaviour matches `expected_behavior`, overall and per tag. An exception SHALL be recorded for that entry and SHALL NOT stop the run.

#### Scenario: Out-of-scope request planned anyway
- **WHEN** an entry tagged `out_of_scope` with `expected_behavior` = `refuse` produces an itinerary
- **THEN** it counts as incorrect behaviour

#### Scenario: Workflow raises
- **WHEN** the workflow raises an exception for one entry
- **THEN** that entry is recorded as `error` and the remaining entries are still evaluated

### Requirement: Clarify expectations
Because no observed behaviour class corresponds to a clarifying question, an entry whose `expected_behavior` is `clarify` SHALL count as incorrect behaviour until a later change defines how a clarification is observed.

#### Scenario: Clarify entry
- **WHEN** an entry with `expected_behavior` = `clarify` produces an itinerary
- **THEN** it counts as incorrect behaviour

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

### Requirement: Judge calibration
The harness SHALL support recording manual scores for a sample of at least 20 itineraries and SHALL report the agreement rate between the judge model and the manual scores alongside the faithfulness metric.

#### Scenario: Agreement reported
- **WHEN** a report includes faithfulness
- **THEN** it also states the calibration sample size and the judge–human agreement rate

### Requirement: Constraint satisfaction metric
The harness SHALL report, for planned itineraries, the share that satisfy each constraint: the number of days equals the requested trip length; the total cost, interpreted as AUD per person excluding accommodation, does not exceed the request's daily budget ceiling multiplied by the trip length; and every attraction is in the requested destination as decided by the judge model.

#### Scenario: Budget exceeded
- **WHEN** a 3-day `budget` request without `max_daily_budget_aud` produces a per-person total above 3 times the configured per-person per-day upper bound for `budget`
- **THEN** that itinerary fails the budget constraint

#### Scenario: Amount in the request
- **WHEN** a 2-day `luxury` entry has `form.max_daily_budget_aud` = 1500 and its itinerary totals 5,000
- **THEN** that itinerary fails the budget constraint

### Requirement: Uncapped budget levels
For a request without a daily budget ceiling (a level with no configured upper bound and no `max_daily_budget_aud`), the budget constraint SHALL be reported as not applicable for that entry and SHALL be left out of the budget constraint share.

#### Scenario: Level without a cap
- **WHEN** a `luxury` request without `max_daily_budget_aud` produces an itinerary
- **THEN** its budget constraint is reported as N/A and the entry is not counted in the budget constraint share

### Requirement: System metrics
The harness SHALL report format pass rate (first validation attempt succeeded), retry rate, the share of requests ending in `error`, p50 and p95 end-to-end latency, and mean cost per request computed from a dated price table in `eval/pricing.yaml`, broken down into generation calls (from recorded token usage), embedding calls (from call counts and input size), and judge calls; the judge cost SHALL be reported separately from the per-request cost.

#### Scenario: Cost computed and broken down
- **WHEN** a run completes
- **THEN** the report shows mean per-request cost split into generation and embedding, the total judge cost, and the date of the price table used

### Requirement: Run and comparison reports
`scripts/eval_run.py` SHALL evaluate one named configuration and store per-entry results and a summary under `eval/runs/<run id>/`, recording the dataset version, corpus version and knowledge table, configuration, model names, template keys and versions, price table date, the git commit SHA, and whether the working tree had uncommitted changes. `scripts/eval_compare.py` SHALL turn several summaries into a Markdown comparison table.

#### Scenario: Comparing two runs
- **WHEN** the baseline run and a later run are compared
- **THEN** the output table has one column per run and one row per metric

#### Scenario: Uncommitted changes
- **WHEN** a run is made while the working tree has uncommitted changes
- **THEN** its summary records `git_dirty` = true and the comparison table marks that run with a warning

### Requirement: Experiment log
Every change that affects quality, behaviour, or cost SHALL add an entry to `docs/experiments.md` containing: the date, the change name, what was changed and why, the run IDs compared, a table of run conditions, the metric comparison table generated from those runs, the conclusion, unexpected results, and the cost in latency, money, and retries. Entries SHALL only be appended; corrections SHALL be new entries that link to the original.

#### Scenario: Entry traceable to runs
- **WHEN** an experiment entry reports a metric
- **THEN** the entry names the run IDs under `eval/runs/` from which that number was generated

#### Scenario: Correction
- **WHEN** an earlier entry is found to be wrong
- **THEN** a new entry is appended that links to it, and the earlier entry is left unchanged

### Requirement: Dataset change log
Every change to `eval/dataset.jsonl` SHALL increase the dataset version and SHALL be recorded in `docs/experiments.md` with the date, the new version, what changed, the reason, and the affected entry IDs.

#### Scenario: Entries added
- **WHEN** three prompt-injection entries are added to the dataset
- **THEN** the dataset version increases and the dataset change log names the three entry IDs

### Requirement: Regression gate
The harness SHALL provide a smoke subset of about 10 entries and a threshold file `eval/thresholds.yaml`; each gated metric's threshold SHALL be either a minimum or a maximum, and running the gate SHALL exit with a non-zero status when any gated metric falls below its minimum or rises above its maximum. Any change to a threshold SHALL be recorded in `docs/experiments.md` with the change that caused it and the reason.

#### Scenario: Metric below threshold
- **WHEN** the smoke run's format pass rate is below its minimum
- **THEN** the gate command exits non-zero and names the failing metric

#### Scenario: Metric above threshold
- **WHEN** the smoke run's error rate is above its maximum
- **THEN** the gate command exits non-zero and names the failing metric

#### Scenario: Intended behaviour change
- **WHEN** a change intentionally lowers a gated metric (for example by refusing out-of-scope requests)
- **THEN** the threshold is updated in the same change and the update is recorded with its reason

### Requirement: Budget amount in the dataset
An entry's `form` MAY contain `max_daily_budget_aud`, an integer of at least 1. The harness SHALL send it with the request; a system without the field ignores it, and its budget constraint is still computed with the amount, as the user asked for it. The dataset SHALL include entries with an amount for each budget level, among them a `luxury` entry and an entry whose amount is above its level's default.

#### Scenario: Amount sent with the request
- **WHEN** an entry with `form.max_daily_budget_aud` is evaluated
- **THEN** the request body contains `max_daily_budget_aud` with that value

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
