# Running the evaluation

How to run the evaluation harness (`build-evaluation-harness`), what a run writes, and how long and how much a run takes. Measured results go in [`experiments.md`](experiments.md); this page only explains how to produce them.

## Commands

```powershell
python scripts/dev.py eval-db-setup                                  # once, and after a migration: create + migrate + seed travel_agent_eval_db
python scripts/eval_dataset_check.py                                 # dataset format and coverage, no API calls
python scripts/eval_run.py --config v010-baseline                    # full run (73 entries)
python scripts/eval_run.py --config v010-baseline --subset smoke     # smoke subset (10 entries)
python scripts/eval_run.py --config <name> --subset dataset-v1      # the 73 dataset-v1 entries, to compare with the v0.1.0 baseline
python scripts/eval_run.py --config <name> --subset budget-amount   # the dataset-v2 entries with a budget amount (e074-e079)
python scripts/eval_compare.py <run id> <run id>                     # Markdown comparison table
python scripts/eval_gate.py                                          # smoke run + thresholds; non-zero exit on failure
```

Needs `EVAL_DATABASE_URL`, `GEMINI_API_KEY` and `OPENAI_API_KEY` in `.env` (see `.env.example`). The app runs in-process against the evaluation database; the development and test databases are never touched. Commit before a run you want to cite: a run on uncommitted code is marked `git_dirty` and is for reference only.

## What a run writes

`eval/runs/<run id>/`, where the run id is `<UTC time>-<config>[-<subset>]`:

| File | Content |
| --- | --- |
| `summary.json` | Run conditions (dataset and corpus version, models, templates, judge prompt versions, price table date, git commit, `git_dirty`), every metric, and `phase_seconds` |
| `results.jsonl` | One line per entry: request, behaviour, all SSE events, retrieval scores, the judge's inputs and verdicts, costs, latencies |
| `judge_prompts/` | A copy of the judge prompt files the run used; with the inputs stored per entry they reproduce every judge prompt exactly |
| `generation_prompts/` | The text of every prompt template version the run used (`<template key>_v<version>.txt`, read from the evaluation database): the generation templates the generate events name, and the correction template that was active when the run started (`conditions.correction_template` in `summary.json`). With the request and step events stored per entry they reproduce every prompt sent to the generation model |

### What is published

| File | Where it lives |
| --- | --- |
| `eval/runs/<run id>/summary.json`, `eval/runs/<run id>/judge_prompts/`, `eval/runs/<run id>/generation_prompts/` | This repository. Every number in `docs/experiments.md` can be traced to a `summary.json` |
| `eval/calibration/<run id>.agreement.json` (the agreement figures `score` prints: per-stratum counts and rates, no text) | This repository. The judge–human agreement in `docs/experiments.md` can be traced to it |
| `eval/runs/<run id>/results.jsonl`, `eval/calibration/<run id>.jsonl` (sample, judge verdicts, human answers), `eval/calibration/<run id>.review.md` | Ignored by git here; copied by hand to a private repository, available on request |

The private files hold model output — every itinerary and knowledge context in full, or claim texts taken from them — and the reviewer's item-by-item answers; nothing in them is secret, but they are large or personal. Only runs with `git_dirty = false` are kept; delete the others.

**After a run that is cited in `docs/experiments.md`**: commit its `summary.json`, `judge_prompts/` and `generation_prompts/` here, copy its `results.jsonl` to the private repository at the same relative path, and push that repository by hand.

**After a calibration**: save the agreement figures with `python scripts/eval_calibration.py score <run id> > eval/calibration/<run id>.agreement.json` and commit that file; copy `<run id>.jsonl` and `<run id>.review.md` to the private repository.

**Keep the local copies.** The calibration script reads `eval/runs/<run id>/results.jsonl`, and so does re-judging a stored run with a new judge prompt (`rebuild-rag` task 2.3). On another machine, copy the files back from the private repository to the same paths before using either.

**Giving someone access**: add them to the private repository as a read-only collaborator and remove them afterwards, or send the files of the runs they asked for. Do not make the repository public temporarily: once public, it can be cloned and forked, and making it private again does not take that back.

**Runs made before `generation_prompts/` existed** (the v0.1.0 baseline runs and `harden-workflow-guardrails` step (a)) were given the directory afterwards with `python scripts/eval_generation_prompts.py <run id> --correction-version N`, which copies the texts from the evaluation database and leaves `summary.json` unchanged; the correction template version is the one active at the run's commit.

## Reading `summary.json`

Rates are fractions between 0 and 1; `null` means there was nothing to measure (for example no entry in that group). Every metric is computed only over the entries it applies to, and the count it was computed over is reported beside it — read the two together, especially on the 10-entry smoke subset, where one entry moves a rate by 10 to 12.5 percentage points.

### Run identity

| Field | Meaning |
| --- | --- |
| `run_id` | `<UTC start time>-<config name>[-<subset>]`; also the directory name |
| `subset` | A subset name from `eval/subsets/` (`smoke`, `dataset-v1`, `budget-amount`), `all`, or `entries` (a debugging run with `--entries`) |
| `entries` | Number of dataset entries sent |
| `started_at`, `finished_at` | UTC timestamps of the run |
| `phase_seconds` | Where the run's time went (see below) |

`phase_seconds`:

| Field | Meaning |
| --- | --- |
| `total` | Wall-clock time of the whole run |
| `requests` | Sum of end-to-end request latencies (requests are sent one at a time, so this is also their wall-clock time) |
| `retrieval_measurement` | Harness-side retrieval measurement: intake, intent matching and retrieval run again for every labelled entry |
| `other_sequential` | The rest of the sequential phase: trace reads and cost calculation |
| `judge_wall` | Wall-clock time of the judge phase, with calls running concurrently |
| `judge_calls_sum` | Sum of the individual judge call latencies; `judge_calls_sum / judge_wall` shows how much the concurrency helped |

### `conditions` — what was measured

Two runs are comparable only when these agree, apart from the one thing the experiment changes.

| Field | Meaning |
| --- | --- |
| `dataset_version`, `corpus_version` | From `eval/dataset_meta.json`; the relevance labels belong to that corpus version |
| `knowledge_table` | The `ai.<table>` the run retrieved from, selected through `KNOWLEDGE_TABLE_NAME` |
| `config` | A full copy of `eval/configs/<name>.yaml` |
| `generation_model`, `embedding_model`, `judge_model` | Models used; the judge is from a different provider than the generator on purpose |
| `judge_prompts` | Judge prompt name → version; the files are copied to `judge_prompts/` |
| `price_table_date` | Date of `eval/pricing.yaml` used for every cost |
| `git_commit`, `git_dirty` | Code version; `git_dirty: true` means uncommitted changes (outside `eval/runs/` and `eval/calibration/`) — reference only, not for formal comparison |
| `generation_templates` | Every prompt template key and version the generate step actually used in this run; their texts are in `generation_prompts/` |
| `correction_template` | Key and version of the `validate_output` correction template active when the run started (validate_output does not report it). Absent in runs made before it was recorded |

### `metrics`

**`slot_extraction`** — Accuracy of a request parser against `gold_slots`, over `plan` entries. `value: null` with a `reason` when the configuration has no parser (v0.1.0).

**`retrieval`** — Measured on every entry with `relevant_sections`, whether or not the workflow would have retrieved for it, using the query the workflow builds.

| Field | Meaning |
| --- | --- |
| `k` | Number of chunks retrieved |
| `entries` | Entries measured (those with relevance labels) |
| `recall_at_k` | Mean share of an entry's relevant sections found in the top k; several chunks of one section count once |
| `mrr_at_k` | Mean of 1 / rank of the first relevant chunk (0 when none is in the top k) |
| `errors` | Entries whose retrieval failed; recorded per entry instead of counting as Recall = 0 |

On the 13-document corpus v1, top 5 covers a large share of the corpus, so Recall and MRR are high; they are expected to drop on a larger corpus.

**`behaviour`** — Whether each request was handled the way the dataset expects (`plan`, `refuse`, `clarify`).

| Field | Meaning |
| --- | --- |
| `overall`, `entries` | Share of all entries whose observed behaviour matches `expected_behavior` |
| `by_expected_behavior` | The same, split by what was expected |
| `by_tag` | The same, per dataset tag (`untagged` for entries without tags) |

Observed behaviour is `plan` (a validated itinerary), `refuse` (422 with a guard `reason`), `invalid_input` (422 without one) or `error`. No observed class corresponds to asking a clarifying question yet, so `clarify` entries always count as incorrect.

**`constraints`** — Checked on planned itineraries only.

| Field | Meaning |
| --- | --- |
| `planned` | Itineraries checked |
| `trip_length_rate` | Share whose number of days equals the requested trip length |
| `budget_rate` | Share whose `total_estimated_cost_aud`, read as AUD per person excluding accommodation, is within the cap in `app/workflow/config.py` × days |
| `budget_entries`, `budget_not_applicable` | Itineraries the budget rate is over, and those left out because their level has no cap (`luxury`) |
| `destination_rate` | Share whose every named place the judge considers in the destination or within a reasonable day trip (departure and return points are not counted) |
| `destination_judged` | Itineraries the judge checked |

**`faithfulness`** — The judge extracts specific claims (opening hours, prices, named places, transport routes and durations) and decides whether the knowledge context the generator was given supports each one; a matching name with a different location is unsupported.

| Field | Meaning |
| --- | --- |
| `overall` | `itineraries`, `claims` and `supported_share` over all judged itineraries |
| `with_context` | The same, for requests that went through retrieval |
| `without_context` | The same, for requests the generator answered with no knowledge context; every claim is unsupported by definition, so expect 0 |
| `judge_errors` | Itineraries the judge could not score after its retries |

`supported_share` measures grounding, not truth: a correct fact that the knowledge base does not contain counts as unsupported. Compare `with_context` across runs; it is the number retrieval changes are expected to move.

**`system`**

| Field | Meaning |
| --- | --- |
| `requests` | Requests sent |
| `format_pass_rate` | Share of requests that reached `validate_output` whose first output passed Pydantic validation |
| `retry_rate` | Share of the same requests that needed the corrective retry |
| `error_rate` | Share of all requests that ended in `error` (error event, unhandled exception, aborted stream); requests are never retried, so failures show here |
| `latency_p50_ms`, `latency_p95_ms` | End-to-end latency percentiles over requests the workflow ran for (HTTP 200); 422 rejections are excluded because they return before the workflow |
| `step_latency_ms` | Per workflow step: `runs` (requests that ran it) and `mean_ms`, from the latency each step writes to its trace row |

**`cost`** — In `currency` (USD) at `price_table_date`.

| Field | Meaning |
| --- | --- |
| `requests` | Requests costed |
| `mean_generation_usd` | Mean generation cost per request, from the token counts on the trace rows (generate plus validate_output's corrective call) |
| `mean_embedding_usd` | Mean embedding cost per request, estimated from the embedded text length (the embedding API reports no token counts) |
| `mean_request_usd` | Mean product cost per request: generation + embedding |
| `requests_missing_usage` | Requests whose generate trace row had no token counts, so their generation cost is understated; expected 0 |
| `judge_calls`, `judge_total_usd` | Number and total cost of judge calls — the cost of evaluating, not of the product, so it is not part of `mean_request_usd` |

## Judge calibration

Faithfulness and the destination check are decided by an LLM judge, so their numbers are only as good as the judge. Calibration measures that: a person reviews a sample of the judge's verdicts and the agreement is reported next to every faithfulness number.

### When to calibrate again

Human labels belong to particular itineraries and a particular knowledge context, so they cannot be reused once those change.

| Change | Recalibrate? |
| --- | --- |
| New judge prompt version, or a different judge model | Yes |
| New corpus version (the context the judge compares against changes) | Yes |
| Changes to the system under test only (templates, routing, guardrails) | No; glance at a few verdicts if the itineraries look very different |
| Changes to how the harness aggregates numbers | No |

A report whose judge setup matches an earlier calibration cites that calibration; otherwise it needs a new one. On the current roadmap that means again at `rebuild-rag` (corpus v2, destination prompt v2).

### How the sample is drawn

```powershell
python scripts/eval_calibration.py sample <run id>     # writes eval/calibration/<run id>.review.md and .jsonl
python scripts/eval_calibration.py review <run id>     # rebuild the review sheet from the .jsonl, keeping answers
python scripts/eval_calibration.py score <run id>      # copy the answers into the .jsonl and print the agreement
```

The sample is stratified, so that the judge's likely mistakes get reviewed without reading every item:

- 20 itineraries drawn at random (fixed seed) from a clean full run;
- in each: **every** claim the judge called supported (where a judge is most likely to be wrong, e.g. a name matched in the wrong city), up to 5 of the claims it called unsupported, and up to 4 places;
- plus every other itinerary of the run with a place the judge put **outside** the destination, reviewed for the destination check only, so both of the judge's answers are checked.

Agreement is reported per stratum (per judge answer), never as one pooled rate, because the strata are not sampled in proportion.

### How to review

Everything is in one file, `eval/calibration/<run id>.review.md`: each itinerary's request, the knowledge context the generator was given, the itinerary, and one line per item with an answer slot:

```
c1  [claim: ?] [supported: ?]   judge: SUPPORTED · named_place · Ngadiku Dreamtime Walk
p1  [in: ?]   judge: in · Daintree Rainforest — 2 hours north of Cairns
missed:
```

Replace each `?` with `y` or `n`; `supported` is `-` when the item is not a claim, and is pre-filled `n` when there was no knowledge context. The judge's answers are shown but never pre-filled into the slots, so they do not anchor the review. `score` copies the answers into `<run id>.jsonl`, the stored record. Decide `supported` only from the knowledge context the file shows, never from what you know about the place; decide `in_destination` with your own geographic knowledge, as the judge does. Only the places listed under **Places** need an `in_destination` answer; a `named_place` claim is judged on `supported` alone:

| Field | Set to `true` when | Set to `false` when |
| --- | --- | --- |
| `is_claim` | The text is one of the four kinds: an opening-hours statement about a place; a specific price of a specific thing (including "free entry" to a named place); a specific named venue, attraction, tour, event, business or named transport service; a specific transport route or duration between places | It is a general description ("enjoy the views", "cheap eats", "a free way to spend the morning"), traveller scheduling ("leave at 9am"), or the itinerary's own cost estimate |
| `supported` (only when `is_claim` is `true`) | The knowledge context states it, or something that directly implies it, **consistently with the itinerary** — the same place, in the same location | The context does not contain it, even if it is true in reality; or the context ties it to a different place (a Sydney tour placed in a Darwin itinerary). With no context, always `false` |
| `in_destination` | The place is in the destination or a reasonable day trip from it for this trip length | It is too far to visit from the destination within this trip. Departure and return points should not appear; if one does, mark it `true` and note it |

**Activities at a place are not claims in judge prompt v1.** In "spot wild koalas at Kennett River", the named place (Kennett River) is a claim; the activity (spotting koalas there) is not. When the judge extracts such a sentence as a `named_place` claim, decide `supported` on the place alone — is it in the context, in the same location — and ignore the activity. This keeps the review consistent with what faithfulness v1 measures. It also means an invented activity at a real place ("swim with dolphins at Bondi") is not caught; a later judge prompt adds an `activity` kind (see `rebuild-rag`).

Also list after `missed:` any claim of the four kinds that the judge did not extract, as short quotes separated by `;`. Under each itinerary's sampled claims, the sheet lists the judge's other (unsampled) claims for reference: a claim in the itinerary that appears in neither list is a missed one. Missed claims are noted when seen while reading, not found by a line-by-line search, so the count is a lower bound; say so when reporting it.

### Review questions and the reasoning behind the answers

Decisions taken while running the first calibration (v0.1.0 baseline, 2026-10-26), kept so later calibrations follow the same reasoning.

**Does the judge only check the sampled items?** No. The judge checks every claim and every place in every itinerary of a run, and every metric is computed from those verdicts. The sample exists only to measure how far the judge can be trusted: like re-marking some of the papers a marker has marked. The review produces no metric of its own; its agreement is reported next to the metrics it qualifies.

**Why is a claim's location checked when it is not a place check?** They are two different questions. `supported` asks whether the context backs the claim *as the itinerary states it*, so a name the context ties to another city is unsupported (the context's Aboriginal Bush Tucker Tour is in Sydney's Royal Botanic Gardens; in a Darwin itinerary it is unsupported). Distance from the destination plays no part. `in_destination` asks whether the itinerary sends the traveller somewhere reachable, and needs geographic knowledge the context does not give. Examples from a Cairns itinerary:

| Item | Answer | Why |
| --- | --- | --- |
| Claim "Daintree Rainforest" | `supported: y` | The context places it "2 hours north of Cairns" |
| Claim "Cairns Museum" | `supported: n` | Not in the context, although it exists and is in Cairns |
| Claim "Hosier Lane" | `supported: n` | The context puts it in Melbourne |
| Place "Daintree Rainforest" | `in: y` | A day trip from Cairns |
| Place "Tower Hill" in a Melbourne trip | `in: n` (if the trip is short) | Several hours from Melbourne; judged with your own knowledge |

**When travel goes from A to B, are A and B claims, places, or both?** Claims and places are separate lists answering different questions. A **claim** is a piece of text: a route with its endpoints ("the 30-minute ferry from Circular Quay to Manly") is one `transport` claim, and its endpoints are not extracted again from that same text; a named place mentioned in a *different* piece of text is its own `named_place` claim, unless it is a place already claimed: a second mention of the same place is not a new claim (the prompt says never to list the same place twice). A **place** is somewhere the itinerary has the traveller visit: a point used only to depart or arrive is not listed, but a place the traveller also spends time at is, even if it is a route's endpoint. Example, Sydney itinerary: "Take the 30-minute ferry from Circular Quay to Manly. Spend the afternoon at Manly Beach and walk to Shelly Beach."

| Item | Claims | Places |
| --- | --- | --- |
| Circular Quay | Part of the `transport` claim, not separate | Not listed: only where the ferry leaves |
| Manly / Manly Beach | "Manly" in the first sentence is part of the `transport` claim; "Manly Beach" in the second is a separate `named_place` claim | Listed: the traveller spends the afternoon there |
| Shelly Beach | A separate `named_place` claim | Listed |

What counts is whether it is the same *place*, not the same words. Examples from the Brisbane itineraries (e038, e058):

| Mentions | Claims | Why |
| --- | --- | --- |
| "a stroll through the South Bank Cultural Precinct" … "a riverside dinner in South Bank" | 1 | The same area mentioned again; the second mention adds no new place, so it is not a missed claim either |
| South Bank Cultural Precinct and the Queensland Art Gallery | 2 | A venue inside the area is a place of its own |
| South Bank and South Bank Parklands | 2 | A named park inside the area is a place of its own |
| "ferry … to Manly" and "Manly Beach" | 2 | The first is part of the `transport` claim; the second is a named attraction |

A `transport` claim's endpoint counts as supported only when the context names that endpoint: "direct train access" from the airport to "the city centre" supports "the train from the airport into the city", but not "the train from the airport to Circular Quay" (e033) — the more specific endpoint comes from the model, even if it is right.

If the judge extracts the *same* text twice — the route as `transport` and "Manly" from that same sentence as `named_place` — mark the duplicate `[claim: n] [supported: -]`: counting one piece of text twice inflates the faithfulness denominator, and the extraction-precision figure should show it. For `supported` on a `transport` claim, the context must back the route itself (the endpoints and any stated duration or service), not merely mention the places. For places, whether the judge lists "Manly" or "Manly Beach" makes no difference to `destination_rate` as long as both are in the destination; only judge each listed place's `in` answer.

**Do private transfers and drives count as `transport`?** The prompt has no special rule for them: every mode is judged the same way. A movement with a mode and a destination, whose origin is stated or clear from the itinerary (the previous stop, the hotel), is a `transport` claim; a duration or distance makes it one too. Supported only when the context states that route (or its duration) for that mode or without naming one.

| Text | `claim` | Why |
| --- | --- | --- |
| "Private seaplane flight to Rottnest Island" (Perth trip) | y | Mode and destination; the origin is Perth |
| "Drive south towards the Swan Valley (approx. 1 hour)" | y | Driving counts like any mode; it also has a duration |
| "Private transfer to the airport for departure" | y | The origin is the hotel |
| "Return by ferry at sunset" | y | Origin and destination follow from the previous sentence (Manly → Circular Quay) |
| "Morning flight back to Adelaide" (after days on Kangaroo Island) | y | The origin is Kangaroo Island; the context's "30-min flight from Adelaide" supports it |
| "Hire a private chauffeur for the day" | n | No specific movement |
| "Nautilus Aviation helicopter" | y, as `named_place` | A named operator is a business, not a route |

**Are seasons claims?** Not in judge prompt v1, unless they say when a place or service operates — that is `opening_hours`. "November to February offers the best weather for beaches" is climate advice and not a claim; "whale-watching tours run June to November" and "the museum closes on Mondays" are `opening_hours`. Seasonal advice can be checked against the context (corpus v1 states seasons), so it is a gap of v1 like activities; v1 is also inconsistent about it (in the baseline the judge filed "barramundi fishing season is prime March-November" under `opening_hours`). `rebuild-rag` adds a `season` kind to faithfulness v2. Until then, review such a claim as the judge filed it.

**Is a named room, suite or outlet inside a venue a separate claim?** Yes when it has a proper name: "the Chairman's Suite at the Langham" is two `named_place` claims, as "HOTA" and "HOTA café", or "Q1 Skypoint" and "Skypoint Bistro", are. A descriptive name is not a claim: in "a premium Harbour View Suite at the Langham" only the hotel is.

**Are apps, operators and organised services claims?** Yes: `named_place` includes businesses and tours.

| Text | Claims | Places |
| --- | --- | --- |
| "use Groupon for deals" | 1 `named_place` (a named business) | Not listed: an app is not somewhere the traveller goes |
| "join the Brisbane City Council walking tours" | 1 `named_place` (a named tour) | Listed: the destination prompt includes tours |
| "the free Brisbane City Council walking tours" | 2: the tour (`named_place`) and "free" (`price`) | Listed |

**Are activities claims?** Not in judge prompt v1 (see above): judge the place, ignore the activity. The gap is recorded in the baseline and closed by the `activity` kind planned for `rebuild-rag`.

**Why stratify instead of reviewing everything?** The first sample had 610 items (2–3 hours). Calibration has to be repeated whenever the judge or the corpus changes, so it must stay affordable; and the review is tied to particular itineraries and contexts, so it cannot be reused later anyway. Every judge-supported claim is reviewed because that is where judge mistakes inflate faithfulness.

**Which files are edited?** Only `<run id>.review.md`. `<run id>.jsonl` is the stored record — the sample and the answers — that `score` writes from the review sheet and that the reported agreement is computed from; keep both and copy them to the private repository, and commit the `.agreement.json` (see "What is published"). Editing the `.jsonl` by hand is overwritten by the next `score`. Before regenerating the sheet (`review`), save and close it and run `score`, so that answers in the sheet reach the `.jsonl` first.

### Reading the result

`score` prints, per stratum, how many items were compared and the agreement:

- `faithfulness.judge_supported` — of the claims the judge called supported, the share the reviewer also calls supported; low values mean faithfulness is **overstated**.
- `faithfulness.judge_unsupported` — the same for unsupported; low values mean faithfulness is **understated**.
- `extraction_precision` and `missed_claims` — how well the judge picks out claims.
- `destination.judge_in` / `destination.judge_out` — the same for the destination check.

If any stratum is below 0.8, improve the judge prompt (a new version) and recalibrate before relying on that metric. Record the result in the baseline or change entry of `experiments.md`, with the sample sizes.

## Time and cost per run

These are **estimates**, computed from per-unit measurements of one smoke run. They are planning figures, not results: do not cite them in `experiments.md`. Recompute them with the formulas below when the models, the prices or the system change, and replace the measurements with those from the latest full run once one exists.

### Per-unit measurements

Source: run `20261026T105704Z-v010-baseline-smoke` (10 entries, commit `88e5ad0`, judge concurrency 4), price table of 2026-10-25.

| Unit | Time | Cost (USD) |
| --- | --- | --- |
| One request to the system, end to end | 4.47 s | 0.00113 |
| ↳ `generate` (Gemini generation call) | 3.13 s | (included above) |
| ↳ `cag_match` (one embedding call) | 0.65 s | |
| ↳ `rag_retrieve` (one embedding call + vector search; retrieval path only) | 0.64 s | |
| Retrieval measurement, per labelled entry (harness side) | 1.36 s | ≈ 0 (embeddings) |
| One judge call (`gpt-6-luna`, ≈ 1,230 input / 1,680 output tokens) | 19.2 s | 0.00096 |

Each planned itinerary gets two judge calls (faithfulness and destination). v0.1.0 produces an itinerary for every request, including the ones it should refuse; once `harden-workflow-guardrails` rejects them with 422, those entries need neither generation nor judging and a run gets cheaper.

### Formulas

With `N` entries, `L` of them with relevance labels, `P` planned itineraries and judge concurrency `C`:

```
time ≈ N × 4.47 s  +  L × 1.36 s  +  (2P × 19.2 s) / C
cost ≈ N × $0.00113  +  2P × $0.00096
```

Requests run one at a time (design decision 28); only the judge phase is divided by `C`, and only as long as the OpenAI rate limit allows it.

### Estimates

| Run | N / L / P | Judge concurrency | Time | Cost (USD) |
| --- | --- | --- | --- | --- |
| Smoke subset | 10 / 7 / 10 | 4 | 2.6 min (measured: 158 s) | 0.03 |
| Smoke subset | 10 / 7 / 10 | 8 | ≈ 1.7 min | 0.03 |
| Full dataset v1 | 73 / 54 / 73 | 4 | ≈ 18 min | ≈ 0.22 |
| Full dataset v1 | 73 / 54 / 73 | 8 | ≈ 12 min | ≈ 0.22 |
| v0.1.0 baseline (2 full runs + 2 smoke runs for the gate) | | 8 | ≈ 28 min | ≈ 0.50 |

The current configuration (`eval/configs/v010-baseline.yaml`) uses judge concurrency 8. Concurrency changes only how long the judge phase takes, not any verdict or metric. Per-step latencies and the phase breakdown of every run are in its `summary.json` (`metrics.system.step_latency_ms`, `phase_seconds`).
