# Running the evaluation

How to run the evaluation harness (`build-evaluation-harness`), what a run writes, and how long and how much a run takes. Measured results go in [`experiments.md`](experiments.md); this page only explains how to produce them.

## Commands

```powershell
python scripts/dev.py eval-db-setup                                  # once, and after a migration: create + migrate + seed travel_agent_eval_db
python scripts/eval_dataset_check.py                                 # dataset format and coverage, no API calls
python scripts/eval_run.py --config v010-baseline                    # full run (73 entries)
python scripts/eval_run.py --config v010-baseline --subset smoke     # smoke subset (10 entries)
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

## Reading `summary.json`

Rates are fractions between 0 and 1; `null` means there was nothing to measure (for example no entry in that group). Every metric is computed only over the entries it applies to, and the count it was computed over is reported beside it — read the two together, especially on the 10-entry smoke subset, where one entry moves a rate by 10 to 12.5 percentage points.

### Run identity

| Field | Meaning |
| --- | --- |
| `run_id` | `<UTC start time>-<config name>[-<subset>]`; also the directory name |
| `subset` | `smoke`, `all`, or `entries` (a debugging run with `--entries`) |
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
| `generation_templates` | Every prompt template key and version the generate step actually used in this run |

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
