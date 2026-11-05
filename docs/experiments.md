# Experiments

This file records the effect of every change that affects quality, behaviour or cost, so the effect of each step can be reviewed later.

**Rules**

1. Every number in a table must come from a real run result under `eval/runs/`, with its run ID noted. Numbers must not be filled in or edited by hand. The run's `summary.json` is in this repository; its per-entry `results.jsonl` is in a private repository, available on request (see `docs/evaluation.md`, "What is published").
2. Runs used for formal comparison must be run on code with **no uncommitted changes** (`git_dirty = false` in the run summary). Runs with uncommitted changes are for reference only and are marked ⚠️.
3. When comparing two runs, apart from "the one thing changed this time", the other conditions (dataset version, corpus version, models, etc.) should be the same; any differences must be stated in the record.
4. Conclusions state "what was seen", not "what we hoped to see". Results with no improvement, or even a regression, are recorded as usual.
5. Records are append-only, never rewritten. If a record is later found to be wrong, append a correction that links to the original record.

---

## How to add a record

1. Run an evaluation before and after the change (for formal comparisons run each configuration 2 times and take the mean):
   ```powershell
   python scripts/eval_run.py --config <config name>
   ```
2. Generate the comparison table:
   ```powershell
   python scripts/eval_compare.py <run ID 1> <run ID 2>
   ```
3. Paste the generated table into the "Records" section below, complete the rest following the template, and add a row to the "Index".
4. If this change intentionally lowers a gate metric, also update `eval/thresholds.yaml` and add a row to the "Threshold change log".
5. If the evaluation dataset was modified, add a row to the "Dataset change log" and bump the dataset version.

---

## Index

| Date | Change | What changed | Key result | Record |
| --- | --- | --- | --- | --- |
| 2026-11-05 | `rebuild-rag` | Step d: Cross-Encoder reranking on the chosen query | Not better: `city` Recall@5 0.514 to 0.501, MRR@5 0.788 to 0.772 with vector candidates (0.490 / 0.772 with BM25 candidates too); adds 286 ms p50 and about 890 MB of memory | [Step d](#2026-11-05--rebuild-rag-step-d--cross-encoder-reranking-on-the-chosen-query) |
| 2026-11-05 | `rebuild-rag` | Query chosen: notes, style and destination, without the category | Group 11 of the comparison; search stays as in step b. The category still sets the generation prompt's tone and constraints | [Query chosen](#2026-11-05--rebuild-rag--query-chosen-notes-style-and-destination-without-the-category) |
| 2026-11-05 | `rebuild-rag` | Query construction: 12 groups of notes, category and search | Best on `city`: notes, no category, vector search, Recall@5 0.457 to 0.514 and MRR@5 0.730 to 0.788 against step b; the gain depends partly on one weakly labelled entry. Notes with today's category lower MRR to 0.692. Decision pending | [Query groups](#2026-11-05--rebuild-rag--query-construction-12-groups-of-notes-category-and-search) |
| 2026-11-04 | `rebuild-rag` | Step c: BM25 + vector + RRF, and Agno hybrid as control | Not better than step b: `city` Recall@5 0.457 to 0.423, MRR@5 0.730 to 0.740. Agno hybrid returned the same chunks as step b for all 54 entries | [Step c](#2026-11-04--rebuild-rag-step-c--bm25-and-vector-fused-with-rrf-and-agno-hybrid-as-control) |
| 2026-11-04 | `rebuild-rag` | Step b: destination filtering | Recall@5 0.519 to 0.609, MRR@5 0.699 to 0.782; all of it from `national_only`, whose 0.969 is inflated by a pool of 9 documents; `city` unchanged at 0.457 / 0.730 | [Step b](#2026-11-04--rebuild-rag-step-b--filter-by-destination) |
| 2026-11-04 | `rebuild-rag` | Step a: vector-only retrieval on corpus v2 | Recall@5 0.519, MRR@5 0.699 (`city` 0.457 / 0.730, `national_only` 0.667 / 0.625); not comparable with corpus v1 numbers | [Step a](#2026-11-04--rebuild-rag-step-a--vector-only-retrieval-on-corpus-v2) |
| 2026-11-04 | `rebuild-rag` | Dataset v3: labels moved to corpus v2. Check before the switch that corpus v1 still gives the same retrieval after the corpus left the code and embedding task types became configurable | Recall@5 0.951 and MRR@5 0.884, unchanged from the final `harden-workflow-guardrails` runs; later v1 configs need a commit from before dataset v3 | [Labels v2](#2026-11-04--rebuild-rag--dataset-v3-labels-for-corpus-v2-and-the-check-before-the-switch) |
| 2026-11-04 | Repository history rewrite | Corpus v1 text removed from all of git history; every commit hash changed | No numbers changed. `git_commit` in earlier run summaries refers to the old hashes | [History rewrite](#2026-11-04--repository-history-rewrite--git_commit-values-in-earlier-runs-use-old-hashes) |
| 2026-11-01 | `true-sse-streaming` | Events streamed as each step finishes; routing decision moved from a Condition evaluator to a plain Step | No evaluation run (not quality-affecting). Manual check: early panels appear quickly, then a visible pause at generate | [Streaming](#2026-11-01--true-sse-streaming--no-evaluation-run-delivery-timing-only) |
| 2026-10-31 | `harden-workflow-guardrails` | Final: input guards, budget amount, 14-day limit (dataset v2, `dataset-v1` subset ×2 + `budget-amount` ×2) | Behaviour correctness 74.0% → 87.7% (`out_of_scope` and `prompt_injection` 0% → 83.3%); days and budget 100%; retry 0.8%, error 0%; faithfulness with context 19.6% on the same itineraries (baseline 23.0%, not met); a loose budget amount raises spending | [Final](#2026-10-31--harden-workflow-guardrails-final--input-guards-budget-amount-and-the-full-change-against-the-baseline) |
| 2026-10-31 | `harden-workflow-guardrails` | (c) response schema + business rules (two runs) | Days and budget 100%, enforced by code; retry 4.8%, all corrections pass, error 0%; p50 3.98 s and $0.00114 per request (both lower than baseline); faithfulness with context 21.5% (baseline 23.0%, not improved) | [(c) rules](#2026-10-31--harden-workflow-guardrails-c--structured-output-and-business-rules) |
| 2026-10-28 | `harden-workflow-guardrails` | (b) daily budget ceiling stated in the generation templates | Within budget 86.5% → 100% (52 / 52) with no retries or extra cost, but some itineraries only lower their estimates (e049, e053); faithfulness with context 19.1% (a: 20.8%, baseline mean 23.0%) | [(b) budget ceiling](#2026-10-28--harden-workflow-guardrails-b--state-the-daily-budget-ceiling-in-the-generation-templates) |
| 2026-10-28 | `harden-workflow-guardrails` | (a) per-person AUD cost unit stated in the templates | Within budget 59.6% → 86.5% (`moderate` median per-person day ~220 → 115 AUD); faithfulness with context 20.8% (baseline 22.2% / 23.8%); cost, retries, errors unchanged | [(a) cost unit](#2026-10-28--harden-workflow-guardrails-a--state-the-per-person-aud-cost-unit-in-the-templates) |
| 2026-10-26 | `build-evaluation-harness` | v0.1.0 baseline | Recall@5 0.951, faithfulness with context 23.0%, within budget 59.6%, behaviour correctness 74.0% (every refuse / clarify entry wrong), p50 4.54 s, $0.00118 per request; judge–human agreement ≥ 88.9% in every stratum | [Baseline](#v010-baseline) |

---

## Record template

Copy the template below, fill it in, and put it at the **top** of the "Records" section (newest first).

````markdown
### YYYY-MM-DD · <change name> · <one sentence on what changed>

- **What changed**: <the specific change, one variable only; if several things changed at once, list them one by one>
- **Why**: <the hypothesis to test, e.g. "filtering by destination reduces retrieving content about other cities">
- **Runs compared**: <run ID before the change> → <run ID after the change>
- **Run conditions**:

  | Item | Before | After |
  | --- | --- | --- |
  | git commit | `abc1234` | `def5678` |
  | Dataset version | v1 | v1 |
  | Corpus version / knowledge-base table | v1 / `travel_docs_v1` | v1 / `travel_docs_v1` |
  | Retrieval configuration | a | b |
  | Generation model / judge model | | |
  | Generation template (key / version) | | |
  | Price table date | | |

- **Results**:

  | Metric | Before | After | Change |
  | --- | --- | --- | --- |
  | (generated by `eval_compare.py`) | | | |

- **Conclusion**: <what was seen. Which metrics changed and by how much; whether the proposal's success criteria were met>
- **Surprises or problems**: <entries that behaved abnormally (with entry ids), unexpected side effects, things to follow up>
- **Cost**: <changes in latency, cost, retry rate>
````

**Metric definitions**: see `openspec/specs/evaluation-harness/spec.md` for the definition of each metric. Tables include at least the metrics relevant to the change and all of the gate's metrics.

---

## Records

### 2026-11-05 · rebuild-rag step d · Cross-Encoder reranking on the chosen query

Runs on commit `410c6d0` (retrieval only, dataset v3, table `travel_docs_v2_c800`, query as group 11, model `cross-encoder/ms-marco-MiniLM-L6-v2` without fine-tuning, on the CPU). The baseline is group 11 re-run on commit `6115846`. 54 labelled entries, no errors. Reranking ran: no entry kept group 11's result and no fallback was logged. Each cell is Recall@5 / MRR@5.

| Configuration | `city` (38) | `city` with notes (14) | `city` without notes (24) | `national_only` (16) | All (54) | Retrieval p50 / p95 | Run ID |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Group 11, no reranking | 0.514 / 0.788 | 0.465 / 0.651 | 0.543 / 0.868 | 0.948 / 0.906 | 0.643 / 0.823 | 619 / 669 ms | `20261105T070231Z-rebuild-rag-q11-retrieval` |
| d, vector candidates | 0.501 / 0.772 | 0.489 / 0.726 | 0.508 / 0.799 | 0.969 / 0.859 | 0.640 / 0.798 | 905 / 1007 ms | `20261105T080155Z-rebuild-rag-d-retrieval` |
| d, vector + BM25 candidates | 0.490 / 0.772 | 0.477 / 0.750 | 0.498 / 0.785 | 0.969 / 0.859 | 0.632 / 0.798 | 1074 / 1248 ms | `20261105T080256Z-rebuild-rag-d-fused-retrieval` |

- **Reranking did not meet the criteria.** On `city`, Recall@5 fell from 0.514 to 0.501 (vector candidates) and 0.490 (vector + BM25 candidates), and MRR@5 from 0.788 to 0.772 in both. Against group 11, Recall rose for 9 entries and fell for 9 with vector candidates, and rose for 10 and fell for 12 with both candidate sets.
- **The result depended on the query.** On `city` entries with notes it improved (vector candidates: 0.465 / 0.651 to 0.489 / 0.726); on those without notes it got worse (0.543 / 0.868 to 0.508 / 0.799). The model was trained on web search questions, so short keyword-like queries are a candidate cause, not an established one.
- **More candidates did not help.** Adding BM25's candidates lowered Recall further, although a separate local check showed the candidates cover more labelled sections (Recall@20 0.699 for vector, 0.789 for both). That check and the figures below are not evaluation runs.
- **Cost.** Added p50 latency was 286 ms with vector candidates and 455 ms with both, within the 1 second limit. On made-up 800-character text in a fresh process on this machine, process memory was about 890 MB working set and 1.3 GB committed, the import took 6 seconds, and the first model load 24 seconds including the download.
- **Environment.** This ran with torch 2.10.0 and transformers 5.17.0 from conda, not the versions pip would resolve for the pin in `pyproject.toml`.

---

### 2026-11-05 · rebuild-rag · query chosen: notes, style and destination, without the category

- **Decision**: the workflow's query is group 11 of the [12-group comparison](#2026-11-05--rebuild-rag--query-construction-12-groups-of-notes-category-and-search): `notes` (if any), `travel_style` and `travel in <destination>`. Search stays as in step b.
- **Why**: no group met the criteria against it, and it is the simplest. The evidence is moderate, as that record says.
- **What this leaves open**: the category still sets the tone and constraints of the generation prompt, matched on the same intent text as before, so a `moderate` request can still get `budget` constraints. Measuring a change there needs generation runs. e042 and the untranslated Chinese notes of e029 and e079 stay as recorded.
- **Naming**: the configuration value `query_category: current` in the summaries of groups 3 to 12 is now called `matched`, because the workflow no longer sends that query. The two mean the same query.

---

### 2026-11-05 · rebuild-rag · query construction: 12 groups of notes, category and search

Retrieval only, dataset v3, table `travel_docs_v2_c800`, destination filter on, 54 labelled entries, no errors. Groups 3 to 12 ran on commit `2d73f89` with `git_dirty` false; groups 1 and 2 are steps b and c. Exact vector scan and a deterministic BM25 order, so each group ran once rather than twice: groups 3 and 4 reproduced an earlier exploratory run's per-entry Recall, and the 30 entries without notes retrieved identical results across every pair of groups differing only in notes.

Three variables: `notes` at the start of the query or not; the category as matched today, matched on an intent text without the budget phrase (`{style} trip to {destination}`), or left out with the word "itinerary"; and search as in step b or step c. The `no budget` and `none` variants exist only in the evaluation harness. Criteria set before the run: `city` Recall@5 and MRR@5 decide, `national_only` must not get worse; a group is better only with Recall at least 0.02 higher and MRR not lower; otherwise the simpler one wins. The 0.02 is a judgement, not a statistical test.

Each cell is Recall@5 / MRR@5.

| Group | Notes | Category | Search | `city` (38) | `national_only` (16) | All (54) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | no | as matched | vector | 0.457 / 0.730 | 0.969 / 0.906 | 0.609 / 0.782 |
| 2 | no | as matched | BM25 + RRF | 0.423 / 0.740 | 0.969 / 0.875 | 0.585 / 0.780 |
| 3 | no | no budget | vector | 0.476 / 0.755 | 0.969 / 0.938 | 0.622 / 0.809 |
| 4 | no | no budget | BM25 + RRF | 0.437 / 0.797 | 0.969 / 0.938 | 0.595 / 0.839 |
| 5 | no | none | vector | 0.477 / 0.772 | 0.969 / 0.906 | 0.623 / 0.812 |
| 6 | no | none | BM25 + RRF | 0.433 / 0.829 | 0.969 / 0.906 | 0.592 / 0.852 |
| 7 | yes | as matched | vector | 0.464 / 0.692 | 0.969 / 0.906 | 0.614 / 0.755 |
| 8 | yes | as matched | BM25 + RRF | 0.441 / 0.659 | 0.979 / 0.896 | 0.600 / 0.729 |
| 9 | yes | no budget | vector | 0.496 / 0.747 | 0.969 / 0.938 | 0.636 / 0.804 |
| 10 | yes | no budget | BM25 + RRF | 0.447 / 0.776 | 0.979 / 0.906 | 0.605 / 0.815 |
| 11 | yes | none | vector | 0.514 / 0.788 | 0.948 / 0.906 | 0.643 / 0.823 |
| 12 | yes | none | BM25 + RRF | 0.455 / 0.812 | 0.979 / 0.927 | 0.610 / 0.846 |

| Group | `city` with notes (14) | `city` without notes (24) | `Sleep` chunks of 190 | Retrieval p50 | Run ID |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.314 / 0.681 | 0.540 / 0.758 | 21 | 624 ms | `20261104T081045Z-rebuild-rag-b-retrieval` |
| 2 | 0.358 / 0.774 | 0.461 / 0.720 | 32 | 656 ms | `20261104T091258Z-rebuild-rag-c-retrieval` |
| 3 | 0.326 / 0.657 | 0.563 / 0.812 | 6 | 641 ms | `20261105T063238Z-rebuild-rag-q3-retrieval` |
| 4 | 0.379 / 0.756 | 0.472 / 0.821 | 8 | 633 ms | `20261105T063352Z-rebuild-rag-q4-retrieval` |
| 5 | 0.364 / 0.607 | 0.543 / 0.868 | 5 | 617 ms | `20261105T063525Z-rebuild-rag-q5-retrieval` |
| 6 | 0.370 / 0.711 | 0.469 / 0.897 | 7 | 639 ms | `20261105T063602Z-rebuild-rag-q6-retrieval` |
| 7 | 0.335 / 0.577 | 0.540 / 0.758 | 17 | 624 ms | `20261105T063641Z-rebuild-rag-q7-retrieval` |
| 8 | 0.406 / 0.554 | 0.461 / 0.720 | 21 | 634 ms | `20261105T063754Z-rebuild-rag-q8-retrieval` |
| 9 | 0.382 / 0.636 | 0.563 / 0.812 | 6 | 606 ms | `20261105T063908Z-rebuild-rag-q9-retrieval` |
| 10 | 0.406 / 0.699 | 0.472 / 0.821 | 5 | 622 ms | `20261105T064017Z-rebuild-rag-q10-retrieval` |
| 11 | 0.465 / 0.651 | 0.543 / 0.868 | 5 | 604 ms | `20261105T064128Z-rebuild-rag-q11-retrieval` |
| 12 | 0.430 / 0.667 | 0.469 / 0.897 | 4 | 618 ms | `20261105T064205Z-rebuild-rag-q12-retrieval` |

Reading across rows of the split table is not meaningful: entries with and without notes are different entries.

Sensitivity of the leading groups (weak labels: e006, e012, e025, e036, e037, e038, e062; deduplicated: entries with the same destination, style and notes count once):

| Group | `city` deduplicated (33) | `city` without weak labels (31) | Both (26) |
| --- | --- | --- | --- |
| 1 | 0.438 / 0.689 | 0.503 / 0.775 | 0.488 / 0.732 |
| 2 | 0.423 / 0.731 | 0.442 / 0.778 | 0.446 / 0.774 |
| 7 | 0.455 / 0.660 | 0.501 / 0.743 | 0.496 / 0.713 |
| 9 | 0.494 / 0.724 | 0.532 / 0.797 | 0.536 / 0.777 |
| 5 | 0.487 / 0.768 | 0.472 / 0.809 | 0.483 / 0.811 |
| 11 | 0.515 / 0.776 | 0.518 / 0.831 | 0.519 / 0.824 |
| 12 | 0.449 / 0.819 | 0.453 / 0.834 | 0.446 / 0.847 |

Paired bootstrap on the deduplicated `city` entries (10,000 samples, not part of the criteria), mean difference and 95% interval:

| Comparison | Recall@5 | MRR@5 |
| --- | --- | --- |
| Group 11 − group 1 | 0.076 (−0.012 to 0.173) | 0.087 (−0.030 to 0.205) |
| Group 11 − group 7 | 0.060 (−0.022 to 0.154) | 0.116 (0.020 to 0.217) |
| Group 11 − group 5 | 0.028 (−0.014 to 0.073) | 0.009 (−0.037 to 0.056) |
| Group 11 − group 9 | 0.021 (−0.045 to 0.102) | 0.052 (−0.019 to 0.128) |
| Group 11 − group 12 | 0.065 (0.015 to 0.115) | −0.043 (−0.143 to 0.061) |

- **Group 11 (notes, no category, vector) has the highest `city` Recall, and no group meets the criteria against it.** It meets them against groups 1, 2, 3, 5, 7, 8 and 10. Against group 9, Recall is 0.018 higher (under 0.02) and MRR 0.041 higher, and group 9 is the more complex one. Against groups 4, 6 and 12 (search as in step c), Recall is 0.077, 0.081 and 0.059 higher but MRR 0.009, 0.041 and 0.024 lower, so neither side meets the criteria and the simpler one wins. Against group 1, Recall rose for 15 entries, fell for 10 and stayed the same for 13.
- **The evidence is moderate.** e038 (a weak label, one labelled section, Recall 0 to 1) is 46% of group 11's net Recall gain over group 1. Without weak labels the Recall gain over group 1 is 0.015, under the criterion, while the MRR gain stays at 0.056. The 95% intervals for group 11 − group 1 include zero.
- **Group 7, which the workflow currently sends after task 4.6, has a lower `city` MRR than group 1:** 0.692 against 0.730, with Recall 0.464 against 0.457. Notes helped when the category was left out (group 5 to 11, entries with notes: Recall 0.364 to 0.465, MRR 0.607 to 0.651), and much less when it stayed (group 1 to 7: Recall 0.314 to 0.335, MRR 0.681 to 0.577).
- **Search as in step c stayed behind on Recall for all three category settings,** with or without notes. Group 12 − group 11 on `city`: Recall −0.059, MRR +0.024. Its MRR lead does not survive as a clear difference in the bootstrap, and the Recall deficit does.
- **The category words were part of the `Sleep` effect:** without today's matched category, `Sleep` chunks fell from 21 to 5 or 6 (b) and from 32 to between 4 and 8 (c), but Recall of c did not catch up with b.
- **`national_only`:** group 11 Recall 0.948 against 0.969, from e042 (Recall 1.0 to 0.67); MRR unchanged at 0.906.
- **Chinese notes hurt:** e029 and e079 (same request, notes in Chinese, not translated) fell from Recall 0.50 to 0.25 once their notes entered the query.
- **Not measured:** generation. These groups say nothing about itinerary quality. Leaving the category out of the query does not change the tone and constraints the category gives the generation prompt.
- **Decision pending.** The query in use stays as task 4.6 built it until the choice is made.

---

### 2026-11-04 · rebuild-rag step c · BM25 and vector fused with RRF, and Agno hybrid as control

Runs `20261104T091258Z-rebuild-rag-c-retrieval` and `20261104T091415Z-rebuild-rag-c-agno-retrieval` (commit `d1da012`, retrieval only, dataset v3, table `travel_docs_v2_c800`). Only change from step b: how the filtered candidates are ranked. 54 labelled entries, no errors. The query is still the fixed concatenation without `notes` (task 4.6).

| Group | Entries | Recall@5 b / c / c′ | MRR@5 b / c / c′ |
| --- | --- | --- | --- |
| All | 54 | 0.609 / 0.585 / 0.609 | 0.782 / 0.780 / 0.782 |
| `city` | 38 | 0.457 / 0.423 / 0.457 | 0.730 / 0.740 / 0.730 |
| `national_only` | 16 | 0.969 / 0.969 / 0.969 | 0.906 / 0.875 / 0.906 |

- **BM25 + RRF did not improve on vector search here.** Of 38 `city` entries, Recall rose for 7, fell for 12 and stayed the same for 19. The share of `Sleep` chunks rose (21 to 32 of 190) and `Go next` fell (30 to 15). Why was not investigated beyond this; the query's filler words ("travel", "itinerary") and missing `notes` are candidate causes, not established ones.
- **Agno hybrid returned exactly step b's chunks for all 54 entries.** Its keyword part uses `websearch_to_tsquery`, which requires every query term, and it matched no chunk for any of the 38 `city` queries, so the score reduces to vector similarity. This says nothing about Agno hybrid on short queries.
- Latency p50 656 ms (c), 648 ms (c′), against 624 ms (b). The c run includes building the BM25 index on first use per destination.

---

### 2026-11-04 · rebuild-rag step b · filter by destination

Run `20261104T081045Z-rebuild-rag-b-retrieval` (commit `9663c0c`, retrieval only, dataset v3, table `travel_docs_v2_c800`). Only change from step a: candidates are restricted to the request's destination and the Australia-wide documents. 54 labelled entries, no errors.

| Group | Entries | Recall@5 (a to b) | MRR@5 (a to b) |
| --- | --- | --- | --- |
| All | 54 | 0.519 to 0.609 | 0.699 to 0.782 |
| `city` | 38 | 0.457 to 0.457 | 0.730 to 0.730 |
| `national_only` | 16 | 0.667 to 0.969 | 0.625 to 0.906 |

- The whole gain comes from `national_only`. Retrieval changed for 14 entries, none of them `city`, as step a predicted: no `city` entry had retrieved another city's chunks.
- **The `national_only` numbers are inflated.** With the filter, these requests choose 5 chunks from only 9 Australia-wide documents, so most labels are found whatever the ranking. Read the rise as "chunks from other cities no longer take the places", not as ranking quality. Steps c and d should be judged on `city`.
- Latency is unchanged: p50 624 ms, p95 652 ms.

---

### 2026-11-04 · rebuild-rag step a · vector-only retrieval on corpus v2

Run `20261104T075807Z-rebuild-rag-a-retrieval` (commit `76a53dc`, retrieval only, dataset v3, table `travel_docs_v2_c800`, 800 characters with 80 overlap, `retrieval` task types). 54 labelled entries, no errors.

| Group | Entries | Recall@5 | MRR@5 |
| --- | --- | --- | --- |
| All | 54 | 0.519 | 0.699 |
| `city` | 38 | 0.457 | 0.730 |
| `national_only` | 16 | 0.667 | 0.625 |

- Retrieve latency p50 633 ms, p95 677 ms, including building the knowledge client on every query as the workflow does.
- Six entries score 0: e010, e018, e020 (`national_only`), e034, e036, e038 (`city`). e036 and e038 are among the weak labels listed under dataset v3.
- For `national_only` entries, 46 of 80 retrieved chunks came from other cities' pages, which step b removes. For `city` entries, none of the 190 page chunks came from another city.

These numbers are not comparable with corpus v1: the corpus and the labels both changed.

**Correction to earlier records**: from `harden-workflow-guardrails` on, the harness built retrieval queries without the destination guard, so the five Chinese-destination entries (e054, e055, e056, e057, e071) were measured with the untranslated name, a query the workflow never sends. This affects only the Recall and MRR of those five entries in those runs; generation and judging went through `POST /generate`. Fixed in `76a53dc`; the earlier numbers are left as recorded and were not recomputed.

---

### 2026-11-04 · rebuild-rag · dataset v3: labels for corpus v2, and the check before the switch

**Check before the switch** (run `20261104T053245Z-harden-workflow-guardrails-dataset-v1`, config `harden-workflow-guardrails`, subset `dataset-v1`, commit `a650229`, no uncommitted code): corpus v1 moved from `scripts/seed.py` to a private file and embedding task types became selectable, with v1 tables staying `semantic`. Compared with the two final `harden-workflow-guardrails` runs:

| Metric | This run | Final harden runs |
| --- | --- | --- |
| Recall@5 | 0.951 | 0.951 / 0.951 |
| MRR@5 | 0.884 | 0.884 / 0.884 |
| Behaviour correctness | 87.7% | 87.7% / 87.7% |
| Days / budget constraints | 100% / 100% | 100% / 100% |
| Faithfulness with context | 20.4% | 20.2% / 19.0% |
| Retry rate | 1.7% | 1.7% / 0% |
| Error rate | 0% | 0% / 0% |
| Latency p50 | 4.64 s | 4.22 s / 4.18 s |

Retrieval is unchanged. Latency is about 0.4 s higher in this single run; the cause was not investigated.

**Budget-amount entries**: in the stored corpus v1 runs (three of the originals, two of the copies), e074–e079 have the same query and the same retrieved sections in the same order as e004, e024, e022, e001, e003 and e029, because the amount is not part of the query. A unit test now holds this. Not yet measured on corpus v2.

**Dataset v3**: labels name a page and section. They were drafted from what the sections contain (lines matching each request's theme, not retrieval results) and reviewed by the user. Australia-wide labels kept from v1 were not re-examined. Coverage of the 60 plan entries: 38 `city`, 16 `national_only`, 6 `none` (all Gold Coast, left out of Recall). Known weak labels, where the corpus has little on the request: e006, e012, e025, e036, e037, e038, e062. Recall on v3 is not comparable with Recall on v2 labels: the corpus and the labels both changed.

**To re-run a corpus v1 configuration** after this: check out a commit from before dataset v3 and restore `data/knowledge/v1/source_documents.json` from the private repository.

---

### 2026-11-04 · repository history rewrite · `git_commit` values in earlier runs use old hashes

**What changed**: the text of corpus v1 was removed from every commit in the repository's history, because corpus text is no longer kept in git (`docs/evaluation.md`, "What is published"). The rewrite changed the hash of all 96 commits. No file under `eval/runs/` was edited, and no run was repeated.

**Effect on earlier records**:
- No recorded number changes. Every run summary, its numbers and its `git_commit` value are as they were.
- The `git_commit` in every summary from before 2026-11-04 is an old hash and does not exist in this repository. The old-to-new mapping is `migration/commit-map` in the private repository.
- Checking out a commit from before the rewrite gives `SOURCE_DOCUMENTS = []` in `scripts/seed.py`: the code of that commit, without its corpus. To re-run an earlier configuration, also restore `data/knowledge/v1/source_documents.json` from the private repository and seed from it. The earlier evaluation database tables are unaffected.
- Pull request numbers in earlier commit messages do not match this repository's pull requests.

---

### 2026-11-01 · true-sse-streaming · no evaluation run (delivery timing only)

**What changed**: `POST /generate` sends each step's SSE event as soon as the step finishes instead of after the whole workflow; the workflow runs off the event loop; the `retrieval_decision` event comes from a plain Step instead of a Condition evaluator's `print()`. The routing threshold, prompts, templates, models and validation rules are unchanged, and the same steps run in the same order with the same event contents.

**Why no evaluation run**: the harness measures what a request produces (retrieval, itinerary content, behaviour, latency of the whole request, cost); none of these is changed by when events reach the client. Decided with the user on 2026-11-01. No numbers are recorded for this change.

**What was checked instead**:
- Unit tests (`tests/test_streaming.py`, real uvicorn server): the first three events arrive while generate is still running; `GET /health` answers during generation; two concurrent requests each receive only their own `session_id`; after a client disconnect, validate_output does not start. All four fail against the previous `main.py`.
- Integration tier: 21 passed, including the golden end-to-end test that asserts all 6 steps.
- Manual check in the browser (Low-confidence preset, by the user): the panels up to `rag_retrieve` appeared quickly one after another, followed by a visible pause before `generate` (the Gemini generation call) and `validate_output`. Not timed; no screenshot kept.

---

### 2026-10-31 · harden-workflow-guardrails (final) · input guards, budget amount and the full change against the baseline

- **What changed since (c)**: the input guards (prompt-injection patterns and the Australian place list, refusing with 422 before the workflow), the optional `max_daily_budget_aud`, `trip_length` limited to 14 days, and the unsupported-specifics rule no longer rejecting the request's own budget figures. Dataset v2 adds six `budget_amount` entries (e074–e079); v1 entries are unchanged.
- **Why**: task 6.3's final comparison of the whole change with the v0.1.0 baseline, and a paired measurement of the budget amount.
- **Runs compared**: baseline runs 1 and 2 and (c) runs 1 and 2 as above → `20261031T114451Z-harden-workflow-guardrails-dataset-v1` (final run 1) and `20261031T115436Z-harden-workflow-guardrails-dataset-v1` (final run 2), subset `dataset-v1` = the 73 v1 entries; `20261031T120629Z-harden-workflow-guardrails-budget-amount` and `20261031T120750Z-harden-workflow-guardrails-budget-amount`, subset `budget-amount` = e074–e079. All four `git_dirty = false`, commit `f77b603`. Smoke run on the same commit, for reference: `20261031T114315Z-harden-workflow-guardrails-smoke`.
- **Run conditions**: as in (c), except git commit `f77b603` and dataset v2 (the `dataset-v1` subset holds exactly the v1 entries).
- **Results** (subset `dataset-v1`, comparable with the baseline):

  | Metric | Baseline (mean of 2) | (c) (mean of 2) | Final run 1 | Final run 2 | Final mean |
  | --- | --- | --- | --- | --- | --- |
  | Behaviour correctness (overall) | 74.0% | 74.0% | 87.7% (64 / 73) | 87.7% (64 / 73) | 87.7% |
  | Behaviour correctness: `out_of_scope` / `prompt_injection` | 0.0% / 0.0% | 0.0% / 0.0% | 83.3% / 83.3% | 83.3% / 83.3% | 83.3% / 83.3% |
  | Behaviour correctness: `mixed_language` / `chinese_destination` | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
  | Behaviour correctness: `contradictory` / `underspecified` | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |
  | Planned itineraries | 73 | 73 | 60 | 60 | 60 |
  | Constraint satisfaction: days | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
  | Constraint satisfaction: budget | 59.6% (of 52) | 100.0% (of 52) | 100.0% (41 / 41) | 100.0% (41 / 41) | 100.0% |
  | Constraint satisfaction: attractions in the destination | 91.1% | 97.3% | 96.7% | 95.0% | 95.9% |
  | Faithfulness (with knowledge context), as reported | 23.0% | 21.5% | 20.2% (135 / 668) | 19.0% (137 / 720) | 19.6% |
  | Faithfulness (with knowledge context), the same 43 itineraries in every run | 23.0% (22.0 / 24.0) | 21.3% (20.0 / 22.6) | 20.2% | 19.0% | 19.6% |
  | Format pass / retry / error rate | 100% / 0% / 0% | 95.2% / 4.8% / 0% | 98.3% / 1.7% / 0% | 100% / 0% / 0% | 99.2% / 0.8% / 0% |
  | End-to-end latency p50 / p95 (requests that ran the workflow) | 4.54 s / 5.51 s | 3.98 s / 5.14 s | 4.22 s / 5.30 s | 4.18 s / 5.18 s | 4.20 s / 5.24 s |
  | Cost per request (all 73, refusals cost nothing) | $0.00118 | $0.00114 | $0.00093 | $0.00091 | $0.00092 |
  | Judge cost (reported separately) | $0.146 | $0.125 | $0.101 | $0.101 | — |

  "The same 43 itineraries" are the entries planned in both final runs that had knowledge context; the per-run claim counts for the baseline and (c) are computed from their `results.jsonl` over those entries. Budget shares are over capped itineraries (`luxury` without an amount is N/A): 41 of the 60 planned here, 52 of 73 before.

  Paired budget amounts (subset `budget-amount` against the same entries without an amount in the final `dataset-v1` runs; totals per person, excluding accommodation, run 1 / run 2):

  | Pair | Request | Daily ceiling without → with amount | Total without amount | Total with amount |
  | --- | --- | --- | --- | --- |
  | e004 → e074 | Brisbane, 2 days, `budget` | 70 → 50 | 65 / 125 | 50 / 45 |
  | e024 → e075 | Hobart, 5 days, `budget` | 70 → 120 | 245 / 235 | 300 / 285 |
  | e022 → e076 | Melbourne, 6 days, `moderate` | 200 → 120 | 420 / 440 | 375 / 340 |
  | e001 → e077 | Sydney, 3 days, `moderate` | 200 → 300 | 380 / 360 | 320 / 360 |
  | e003 → e078 | Gold Coast, 5 days, `luxury` | none → 1,500 | 4,500 / 3,550 | 5,900 / 6,800 |
  | e029 → e079 | Cairns, 5 days, `luxury` | none → 600 | 11,800 / 10,000 | 2,900 / 3,000 |

  All 12 itineraries with an amount are within their ceiling, with no retry and no error (both `budget-amount` runs: days, budget and attractions 100%, retry 0%).

- **Conclusion against the proposal's success criteria**:
  - Days and within budget reach 100%: **met**, in both final runs and in the `budget-amount` runs, enforced by code since (c).
  - `out_of_scope` behaviour improves: **met**, 0% → 83.3% (5 of 6 refused with `destination_out_of_scope`; e047 is the known miss). Every `prompt_injection` entry whose injection is in a request field is blocked: **met**, 5 of 5 (e058, injection in `notes`, is not applicable). `mixed_language` does not drop: **met**, 100%.
  - Faithfulness improves: **not met**. On the same 43 itineraries it is 23.0% for the baseline, 21.3% for (c) and 19.6% for the final runs; every harden run since (a) is below the baseline mean (one, (c) run 2 at 22.7% as reported, is above baseline run 1 at 22.2%). The final runs are lower than (c) although nothing between them should touch generation (run-to-run spreads 2.6 and 1.2 pp), so that part is likely noise; taken over all six runs the drop from the baseline is about 2–3 pp.
  - The budget effect is reported in steps: **met**, records (a), (b), (c).
  - Retry rate and latency are reported: retry 0.8%, all corrections pass, no errors; p50 4.20 s against 4.54 s for the baseline; no gate threshold changed.
  - Behaviour correctness overall rises from 74.0% to 87.7%. The nine wrong entries per run: seven `clarify` entries, which no system behaviour can satisfy yet (four planned — e014, e032, e049, e050 — and three refused as out of scope — e048, e072, e073, the vague destinations), and the known misses e047 and e058.
- **Surprises or problems**:
  - **A loose ceiling raises spending.** e078's 1,500 a day takes the Gold Coast trip from 4,500 / 3,550 to 5,900 / 6,800, against no ceiling at all for the same request without an amount; the stated number works as a target as well as a limit. A tight ceiling is followed to the edge: e079 totals 2,900 / 3,000 against a trip ceiling of 3,000, down from 11,800 / 10,000. Whether those amounts are plausible for the activities planned is not checked (roadmap item 4).
  - Cost per request falls to $0.00092 because the 13 refused requests cost nothing; per planned itinerary it is about $0.00112, the same as (c).
  - The retry rate falls from 4.8% in (c) to 0.8%. Part of it is the fix for the request's own budget figures (two of (c)'s seven retries) and the refused requests no longer reaching generation (e045 and e052 retried in (c)); the rest is within what one run to the next can show.
  - p50 latency is 0.2 s higher than in (c) for the same generation code; the set of requests timed changed (refusals return before the workflow and are not timed), and the difference is small, so it is not attributed.
- **Cost**: the four final runs and the smoke run together cost about $0.42 (generation about $0.14, judge about $0.25, smoke about $0.03).

### 2026-10-31 · harden-workflow-guardrails (c) · structured output and business rules

- **What changed** (two things, both in this step): (1) the generate and correction calls request JSON with `ItineraryOutput` as Gemini's response schema (task section 3); (2) after schema validation, `validate_output` checks four business rules — the day count against the request, daily costs adding up to the total, the total within the daily ceiling times the days, and no opening hours or prices in the text that the retrieved chunks do not state — and a failure enters the existing correction call (task section 4). Templates are unchanged from (b) (generation v3, correction v2).
- **Why**: the rules make the constraints code-checked instead of relying on the model; step (c) of task 6.3 measures what they add after (a) and (b), and what they cost in retries and latency. The response schema is in the same step because it landed before the rules; the 3.1 experiment showed it shortens output by about 15%, so latency, cost and claim counts below carry both effects.
- **Runs compared**: baseline runs 1 and 2, (a) and (b) as above → `20261031T012134Z-harden-workflow-guardrails` (run 1) and `20261031T013206Z-harden-workflow-guardrails` (run 2), both `git_dirty = false`, commit `95f8583`. Smoke run on the same commit, for reference: `20261031T011951Z-harden-workflow-guardrails-smoke`.
- **Run conditions**: as in (b), except git commit `95f8583`.
- **Results**:

  | Metric | Baseline (mean of 2) | (a) | (b) | (c) run 1 | (c) run 2 | (c) mean |
  | --- | --- | --- | --- | --- | --- | --- |
  | Recall@5 / MRR@5 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | — |
  | Faithfulness (with knowledge context) | 23.0% | 20.8% | 19.1% | 20.3% (166 / 816) | 22.7% (179 / 789) | 21.5% |
  | Faithfulness (without knowledge context) | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
  | Constraint satisfaction: days | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
  | Constraint satisfaction: budget (52 capped entries) | 59.6% | 86.5% | 100.0% | 100.0% (52 / 52) | 100.0% (52 / 52) | 100.0% |
  | Constraint satisfaction: attractions in the destination | 91.1% | 97.3% | 97.3% | 97.3% | 97.3% | 97.3% |
  | Behaviour correctness (overall; every tag) | 74.0% | 74.0% | 74.0% | 74.0% | 74.0% | 74.0% |
  | Format pass rate (first validation passed) | 100.0% | 100.0% | 100.0% | 94.5% | 95.9% | 95.2% |
  | Retry rate | 0.0% | 0.0% | 0.0% | 5.5% (4 / 73) | 4.1% (3 / 73) | 4.8% |
  | Error rate | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
  | End-to-end latency p50 / p95 | 4.54 s / 5.51 s | 4.32 s / 5.30 s | 4.30 s / 5.34 s | 4.02 s / 5.07 s | 3.93 s / 5.21 s | 3.98 s / 5.14 s |
  | Mean step latency: `generate` / `validate_output` | 3244 / 0 ms | 3097 / 0 ms | 3117 / 0 ms | 2738 / 111 ms | 2750 / 91 ms | 2744 / 101 ms |
  | Cost per request (generation + embedding, incl. corrections) | $0.00118 | $0.00118 | $0.00119 | $0.00113 | $0.00114 | $0.00114 |
  | Judge cost (reported separately) | $0.146 | $0.142 | $0.149 | $0.127 | $0.124 | — |

  The baseline column is the mean of runs 1 and 2 in the baseline record. Which rules fired on the first validation, found by re-running the rules on each run's stored `generate` output with the context rebuilt from its events (every correction then passed, so every retried request completed with `degraded_mode` true):

  | Run | Entry | Rule | Detail |
  | --- | --- | --- | --- |
  | 1 | e024, e034 | unsupported | price $70 not in the retrieved chunks |
  | 1 | e045 (`out_of_scope`, no context) | unsupported | price $10 |
  | 1 | e057 (`chinese_destination`) | unsupported | price $30 |
  | 2 | e026 | unsupported | price $15 |
  | 2 | e052 (`prompt_injection`) | unsupported | prices $4, $10, $15, $18, $20, $25 |
  | 2 | e073 (`underspecified`, luxury) | cost | daily costs 15,500, total 15,700 |

  Faithfulness claims with knowledge context, supported / extracted: run 1 `named_place` 160 / 677, `transport` 5 / 84, `price` 0 / 46, `opening_hours` 1 / 9; run 2 175 / 663, 4 / 73, 0 / 46, 0 / 7 (baseline run 1: 207 / 767, 7 / 105, 0 / 77, 0 / 13). Per-person daily cost, median / max: `budget` 47 / 65 and 55 / 65, `moderate` 132 / 189 and 126 / 199, `luxury` 2,107 / 3,100 and 1,857 / 4,500.

- **Conclusion**: the proposal's constraint criterion holds with the rules on: days and budget are 100% in both runs, now enforced by code rather than by the model following the prompt (the budget rule never had to fire, since (b)'s ceiling in the prompt already kept every itinerary under it). The rules cost little: 3–4 of 73 requests needed one correction call, every correction passed, and no request ended in error. Latency and cost went down, not up (p50 3.98 s against 4.54 s for the baseline, $0.00114 against $0.00118), because the response schema shortens the output (`generate` −500 ms) by more than the corrections add. **Faithfulness did not improve**: the (c) mean, 21.5%, is below the baseline mean, 23.0%, with a run-to-run spread of 2.4 pp in (c) and 1.6 pp in the baseline; it is back up from (b)'s single run (19.1%). The proposal's "faithfulness improves" criterion is not met by sections 1–4.
- **Surprises or problems**:
  - The unsupported-specifics rule catches only amounts written as currency in the text (6 of the 7 retries). The judge still finds 46 price claims per run, none supported: it also counts prices without a currency marker and the per-day estimates the rule exempts on purpose. The rule removed some unsupported prices, not the judge's price category.
  - The cost rule fired once in 146 requests (e073), and the correction fixed it; keeping it in the correction flow (design decision 5) stands.
  - Fewer claims are extracted (about 800 with context against about 940 in the baseline), consistent with shorter output; supported `named_place` claims fall more (about 168 against 210). Whether shorter itineraries name fewer corpus places or the judge extracts differently from them is not separated here; `rebuild-rag` changes the corpus and re-judges with faithfulness v2.
  - e045, e052 and e073 are refuse / clarify entries that were planned and then corrected; section 5's guards stop e045 (Bali) and e052 before generation.
- **Cost**: per request $0.00114 (corrections included) and p50 3.98 s, both lower than every earlier step. The smoke gate's `format_pass_rate` threshold (0.9) now has less headroom: one retry in the 10 smoke entries puts it at exactly 0.9. Not changed; revisit if the gate starts failing on single retries.

### 2026-10-28 · harden-workflow-guardrails (b) · state the daily budget ceiling in the generation templates

- **What changed**: one sentence added after the cost-unit sentence in both generation templates (version 3): "Daily budget ceiling: {daily_budget_ceiling}. If a ceiling is set, keep "total_estimated_cost_aud" at or below that ceiling multiplied by {trip_length} days." The generate step fills the placeholder with the request's daily ceiling (`budget` 70, `moderate` 200 AUD per person per day, excluding accommodation; `luxury` "none set"; no request in dataset v1 sets its own amount). The correction template stays at version 2. The commit also contains task 6.6 (the run directory stores `generation_prompts/`), which changes no output.
- **Why**: in (a) the model knew the unit but not the number the budget constraint holds it to. Step (b) of task 6.3 measures the ceiling in the prompt alone, before the budget rule (c).
- **Runs compared**: baseline runs 1 and 2 (`20261026T111928Z-v010-baseline`, `20261026T113131Z-v010-baseline`) and (a) (`20261028T131648Z-harden-workflow-guardrails`) → `20261028T154638Z-harden-workflow-guardrails` (one run, `git_dirty = false`). Smoke run on the same commit, for reference: `20261028T154420Z-harden-workflow-guardrails-smoke`.
- **Run conditions**: as in (a), except git commit `49d8493`, generation templates `high_confidence_minimal_context` v3 and `low_confidence_with_retrieval` v3, correction template `validate_output_correction` v2 (now recorded in `summary.json`; it was also v2 in (a)).
- **Results**:

  | Metric | Baseline run 1 | Baseline run 2 | (a) | (b) | (b) vs (a) |
  | --- | --- | --- | --- | --- | --- |
  | Recall@5 / MRR@5 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | — |
  | Faithfulness (with knowledge context) | 22.2% (214 / 962) | 23.8% (219 / 919) | 20.8% (196 / 944) | 19.1% (191 / 1001) | −1.7 pp |
  | Faithfulness (without knowledge context) | 0.0% | 0.0% | 0.0% | 0.0% | — |
  | Constraint satisfaction: days | 100.0% | 100.0% | 100.0% | 100.0% | — |
  | Constraint satisfaction: budget (52 capped entries) | 57.7% (30 / 52) | 61.5% (32 / 52) | 86.5% (45 / 52) | 100.0% (52 / 52) | +13.5 pp |
  | Constraint satisfaction: attractions in the destination | 91.8% | 90.4% | 97.3% | 97.3% (71 / 73) | — |
  | Behaviour correctness (overall; every tag) | 74.0% | 74.0% | 74.0% | 74.0% | — |
  | Format pass / retry / error rate | 100% / 0% / 0% | 100% / 0% / 0% | 100% / 0% / 0% | 100% / 0% / 0% | — |
  | End-to-end latency p50 / p95 | 4.56 s / 5.47 s | 4.51 s / 5.54 s | 4.32 s / 5.30 s | 4.30 s / 5.34 s | — |
  | Cost per request (generation + embedding) | $0.00118 | $0.00118 | $0.00118 | $0.00119 | — |
  | Judge cost (reported separately) | $0.148 | $0.144 | $0.142 | $0.149 | — |

  Per-person daily cost by budget level (median / max; "near cap" = within 5% below it), computed from each run's `results.jsonl`:

  | Level (itineraries) | Cap | Baseline run 1 | Baseline run 2 | (a) | (b) |
  | --- | --- | --- | --- | --- | --- |
  | `budget` (18) | 70 | 49 / 5,333 | 48 / 3,833 | 40 / 2,417 | 56 / 67 (near cap: 2) |
  | `moderate` (34) | 200 | 220 / 3,000 | 217 / 3,250 | 115 / 2,375 | 136 / 192 (near cap: 1) |
  | `luxury` (21) | none | 5,114 / 10,571 | 4,600 / 14,250 | 2,171 / 3,720 | 2,386 / 4,500 |

  Faithfulness claims with knowledge context, supported / extracted, by category:

  | Category | Baseline run 1 | Baseline run 2 | (a) | (b) |
  | --- | --- | --- | --- | --- |
  | `named_place` | 207 / 767 | 213 / 753 | 191 / 769 | 183 / 808 |
  | `transport` | 7 / 105 | 6 / 89 | 5 / 105 | 7 / 105 |
  | `price` | 0 / 77 | 0 / 70 | 0 / 59 | 0 / 70 |
  | `opening_hours` | 0 / 13 | 0 / 7 | 0 / 11 | 1 / 18 |

- **Conclusion**: with the ceiling in the prompt every capped itinerary is within budget (52 / 52, from 45 / 52 in (a)), with no retries, no extra cost and no latency change. Costs do not crowd the cap: the `moderate` median rises a little (115 → 136) and only 3 of 52 itineraries are within 5% of it. The proposal's "within budget reaches 100%" is met at this step, before any rule. Faithfulness with context keeps falling (baseline mean 23.0% → (a) 20.8% → (b) 19.1%); see below.
- **Surprises or problems**:
  - **Part of the 100% is lower numbers, not cheaper plans.** e049 (`contradictory`: a budget trip with a five-star hotel and a private chauffeur) now totals 202 AUD for 3 days (65–69 per day) while still planning a private chauffeur, an exclusive Bush Tucker tour and a private water taxi; e053 (`prompt_injection`) totals 770 for 4 days (185–200 per day) with private transfers and a private luxury catamaran charter to the outer reef. The budget constraint checks the model's own estimates against the cap, so an implausibly low estimate passes. This is the "plausible costs" gap already recorded under roadmap item 4; neither (c)'s budget rule nor anything else in this change can detect it. e049 and e053 are clarify / refuse entries; section 5's injection guard stops e053.
  - e009 (barramundi fishing, `moderate`, 2 days) kept the fishing: a half-day guided charter on day 1 (180 AUD) and land-based fishing on day 2 (120), instead of a full-day charter on day 1 in (a). The preference survives; whether a half-day barramundi charter costs that little is again a plausibility question.
  - Faithfulness: supported `named_place` claims fall from about 210 (baseline) to 191 (a) and 183 (b) while the number of extracted claims stays level or rises (about 760 → 808). The drop is spread thinly (the eight entries with the largest drops lose 1.5–4 supported claims each against the baseline mean; 25.5 in total), and the supported places that appear less often mix paid tours from the corpus (Aboriginal Bush Tucker Tour, Worn Gundidj at Tower Hill, Yura Malka Cultural Walk) with places that have nothing to do with cost (SYD airport, Paddington, jacaranda season). One run per step cannot separate a trend from noise; (c) runs twice. If it holds, a likely reading is that the cost sentences push the model toward free, generic sights the corpus does not cover. Two of the paid tours named are the out-of-destination cases from the baseline, which may also explain the higher "attractions in the destination".
- **Cost**: unchanged ($0.00119 per request, p50 4.30 s, retry rate 0%). The ceiling costs nothing at this step; correction calls start with (c)'s rules.

### 2026-10-28 · harden-workflow-guardrails (a) · state the per-person AUD cost unit in the templates

- **What changed**: one sentence added to all three templates (version 2): "All costs are AUD per person, excluding accommodation: "estimated_cost_aud" is what one traveller spends that day, and "total_estimated_cost_aud" is what one traveller spends over the whole trip." Nothing else in the prompts changed. The commit also contains the error handling of task section 1, which changes no output when no call fails (error rate 0% in every run), and the single-active-template migration.
- **Why**: the v0.1.0 templates never say what a cost covers, while the budget constraint reads costs as per person, excluding accommodation. Step (a) of task 6.3 measures the unit alone, before the ceiling goes into the prompt (b) and before the rules (c).
- **Runs compared**: `20261026T111928Z-v010-baseline`, `20261026T113131Z-v010-baseline` (baseline runs 1 and 2) → `20261028T131648Z-harden-workflow-guardrails` (one run, `git_dirty = false`). Smoke run on the same commit, for reference: `20261028T131430Z-harden-workflow-guardrails-smoke`.
- **Run conditions**:

  | Item | Before | After |
  | --- | --- | --- |
  | git commit | `54c17c6` | `4c53305` |
  | Dataset version | v1 (73 entries) | v1 (73 entries) |
  | Corpus version / knowledge-base table | v1 / `travel_docs_v1` | v1 / `travel_docs_v1` |
  | Retrieval configuration | v0.1.0 (k = 5) | v0.1.0 (k = 5) |
  | Generation model / judge model | `gemini-3.1-flash-lite` / `gpt-6-luna` (faithfulness v1, destination v1) | same |
  | Generation template (key / version) | `high_confidence_minimal_context` v1, `low_confidence_with_retrieval` v1 | `high_confidence_minimal_context` v2, `low_confidence_with_retrieval` v2 |
  | Price table date | 2026-10-25 | 2026-10-25 |

- **Results**:

  | Metric | Baseline run 1 | Baseline run 2 | (a) | Change vs baseline mean |
  | --- | --- | --- | --- | --- |
  | Recall@5 / MRR@5 | 0.951 / 0.884 | 0.951 / 0.884 | 0.951 / 0.884 | — |
  | Faithfulness (with knowledge context) | 22.2% (214 / 962) | 23.8% (219 / 919) | 20.8% (196 / 944) | −2.2 pp |
  | Faithfulness (without knowledge context) | 0.0% (0 / 475) | 0.0% (0 / 462) | 0.0% (0 / 445) | — |
  | Constraint satisfaction: days | 100.0% | 100.0% | 100.0% | — |
  | Constraint satisfaction: budget (52 capped entries) | 57.7% (30 / 52) | 61.5% (32 / 52) | 86.5% (45 / 52) | +26.9 pp |
  | Constraint satisfaction: attractions in the destination | 91.8% (67 / 73) | 90.4% (66 / 73) | 97.3% (71 / 73) | +6.2 pp |
  | Behaviour correctness (overall; every tag) | 74.0% | 74.0% | 74.0% | — |
  | Format pass / retry / error rate | 100% / 0% / 0% | 100% / 0% / 0% | 100% / 0% / 0% | — |
  | End-to-end latency p50 / p95 | 4.56 s / 5.47 s | 4.51 s / 5.54 s | 4.32 s / 5.30 s | −0.22 s / −0.21 s |
  | Mean step latency: `generate` | 3227 ms | 3260 ms | 3097 ms | −147 ms |
  | Cost per request (generation + embedding) | $0.00118 | $0.00118 | $0.00118 | — |
  | Judge cost (reported separately) | $0.148 | $0.144 | $0.142 | — |

  Per-person daily cost (`total_estimated_cost_aud` / trip length) by budget level, computed from each run's `results.jsonl`:

  | Level (itineraries) | Cap | Baseline run 1: median / max / over cap | Baseline run 2 | (a) |
  | --- | --- | --- | --- | --- |
  | `budget` (18) | 70 | 49 / 5,333 / 3 | 48 / 3,833 / 2 | 40 / 2,417 / 2 |
  | `moderate` (34) | 200 | 220 / 3,000 / 19 | 217 / 3,250 / 18 | 115 / 2,375 / 5 |
  | `luxury` (21) | none | 5,114 / 10,571 / — | 4,600 / 14,250 / — | 2,171 / 3,720 / — |

- **Conclusion**: stating the unit alone moves "within budget" from 59.6% (baseline mean) to 86.5%, with no change in cost, retries or errors. The gain is almost all `moderate`: the median per-person day halves (about 220 → 115 AUD) and itineraries over the cap drop from 18–19 to 5. That fits the model having estimated for the whole party before; `luxury` medians also halve (about 4,900 → 2,171). Days stay at 100%. This is one run against two baseline runs; the budget gain (+25 pp over the better baseline run) is far outside the baseline's run-to-run spread (3.8 pp).
- **Surprises or problems**:
  - Still over the cap (7): e006, e009, e016, e047 (`moderate`, 215–350 AUD per day), e015 (`budget`, 107), and the two extreme cases from the baseline, e049 (`contradictory`, a budget trip with a five-star hotel and a chauffeur, 2,417 per day) and e053 (`prompt_injection`, 2,375 per day). e015, e047, e049 and e053 are refuse / clarify entries that the input guardrails (section 5) or later changes should stop before planning. The model has not been told the cap yet; step (b) adds it.
  - Faithfulness with context is 20.8%, 1.4 pp below the lower baseline run (spread between the two baseline runs: 1.6 pp). With one run this is not distinguishable from noise; whether it holds is checked again in (b) and in (c), which runs twice.
  - Attractions in the destination rose to 97.3% (71 / 73) from 91.8% / 90.4%. Nothing in this change targets it; the out-of-destination cases in the baseline came from the Indigenous walking tours document. Treated as noise until another run repeats it.
- **Cost**: unchanged at $0.00118 per request; p50 latency 4.32 s, slightly lower, consistent with the `generate` step (−147 ms). Retry rate stays 0%, so the sentence adds no correction calls.

### v0.1.0 baseline

> Run on the commit where the harness implementation is complete (`54c17c6`): relative to tag `v0.1.0` this commit only adds measurement code plus the default generation model change (`gemini-2.0-flash` was shut down), and the system behaviour is the same as v0.1.0 (corpus v1, confidence-based routing, two generation templates).

- **Runs**: `20261026T111928Z-v010-baseline` (run 1), `20261026T113131Z-v010-baseline` (run 2); both `git_dirty = false`
- **Run conditions**: git commit `54c17c6` · dataset v1 (73 entries) · corpus v1 / `travel_docs_v1` · generation model `gemini-3.1-flash-lite` · embedding model `gemini-embedding-001` · judge model `gpt-6-luna` (prompts faithfulness v1, destination v1) · generation templates `high_confidence_minimal_context` v1 and `low_confidence_with_retrieval` v1 · price table date 2026-10-25
- **Notes**:
  - The baseline generates with `gemini-3.1-flash-lite`, not v0.1.0's default `gemini-2.0-flash`, which Google shut down on 2026-06-01 (design decision 16).
  - The v0.1.0 template says "for a traveller" without stating the cost unit; the evaluation interprets costs as "per person, in AUD, excluding accommodation" against the caps in `app/workflow/config.py` (budget 70, moderate 200 per day; luxury has no cap). The prompt never states these caps either — it says only "a moderate budget" — so the baseline's budget constraint measures how often the model's own estimate happens to fall under a number it was not given. `harden-workflow-guardrails` puts the ceiling in the prompt and lets the user set it (design decision 13).
  - `mixed_language` entries are not distinguished from ordinary ones in the baseline: v0.1.0 reads only the form, whose destination is English for these entries (design decision 23).
  - 52 of the 73 requests took the retrieval path (confidence < 0.85) and 21 did not; faithfulness is reported separately for the two groups.

| Stage | Metric | Run 1 | Run 2 | Mean |
| --- | --- | --- | --- | --- |
| Request parsing | Slot extraction accuracy | N/A (no request parser) | N/A | N/A |
| Retrieval | Recall@5 (54 labelled entries) | 0.951 | 0.951 | 0.951 |
| Retrieval | MRR@5 | 0.884 | 0.884 | 0.884 |
| Generation | Faithfulness (with knowledge context) | 22.2% (214 / 962 claims) | 23.8% (219 / 919) | 23.0% |
| Generation | Faithfulness (without knowledge context) | 0.0% (0 / 475) | 0.0% (0 / 462) | 0.0% |
| Generation | Constraint satisfaction: days | 100.0% | 100.0% | 100.0% |
| Generation | Constraint satisfaction: budget (52 capped entries) | 57.7% (30 / 52) | 61.5% (32 / 52) | 59.6% |
| Generation | Constraint satisfaction: attractions in the destination | 91.8% (67 / 73) | 90.4% (66 / 73) | 91.1% |
| Behaviour | Behaviour correctness (overall) | 74.0% | 74.0% | 74.0% |
| Behaviour | Behaviour correctness (`out_of_scope`) | 0.0% | 0.0% | 0.0% |
| Behaviour | Behaviour correctness (`contradictory`) | 0.0% | 0.0% | 0.0% |
| Behaviour | Behaviour correctness (`underspecified`) | 0.0% | 0.0% | 0.0% |
| Behaviour | Behaviour correctness (`prompt_injection`) | 0.0% | 0.0% | 0.0% |
| Behaviour | Behaviour correctness (`mixed_language`) | 100.0% | 100.0% | 100.0% |
| Behaviour | Behaviour correctness (`chinese_destination`) | 100.0% | 100.0% | 100.0% |
| System | Format pass rate | 100.0% | 100.0% | 100.0% |
| System | Retry rate | 0.0% | 0.0% | 0.0% |
| System | Error rate | 0.0% | 0.0% | 0.0% |
| System | End-to-end latency p50 / p95 | 4.56 s / 5.47 s | 4.51 s / 5.54 s | 4.54 s / 5.51 s |
| System | Mean step latency: `generate` / `cag_match` / `rag_retrieve` | 3227 / 643 / 639 ms | 3260 / 649 / 646 ms | 3244 / 646 / 643 ms |
| System | Cost per request (generation + embedding) | $0.00118 | $0.00118 | $0.00118 |
| — | Judge cost (reported separately) | $0.148 | $0.144 | $0.146 |
| — | Judge–human agreement: faithfulness, judge-supported claims | 98.8% (82) | not calibrated | — |
| — | Judge–human agreement: faithfulness, judge-unsupported claims | 96.9% (98) | not calibrated | — |
| — | Judge claim extraction precision (missed claims, lower bound) | 97.8% of 184 (10 missed) | not calibrated | — |
| — | Judge–human agreement: destination, judge-in places | 100.0% (80) | not calibrated | — |
| — | Judge–human agreement: destination, judge-out places | 88.9% (9) | not calibrated | — |

- **Conclusion**: v0.1.0 produces a well-formed itinerary of the right length for every request (format pass 100%, retry 0%, error 0%), including the 19 it should refuse or clarify, so behaviour correctness is exactly the share of `plan` entries (54 / 73). On the 13-document corpus retrieval finds nearly every labelled section (Recall@5 0.951), but even with that context only about a quarter of the itineraries' specific claims are supported by it; the 21 requests on the high-confidence path get no context at all. About 40% of capped itineraries exceed the per-person budget cap.
- **Surprises or problems**:
  - Faithfulness v1 checks four kinds of claims (opening hours, prices, named places, transport routes and durations). Activities at a place are not among them, so an invented activity at a real place ("swim with dolphins at Bondi") counts as a supported `named_place` claim when the place is in the context. The baseline faithfulness numbers carry this limitation; Seasonal statements ("the best months for X") are not a kind either. `rebuild-rag` adds `activity` and `season` kinds in a new judge prompt version and re-judges this baseline with it from the stored results.
  - The budget constraint checks only an upper bound on the model's own cost estimates, which nothing grounds (the corpus has no prices): an unrealistically low estimate passes, and the 21 `luxury` itineraries are not checked at all (e007: 6,500–12,000 AUD per person per day). Nor does anything check that a day's plan fits in a day (e007 day 2: helicopter Perth–Margaret River and back, vineyard tour, coastal drive and spa). Both are recorded under roadmap item 4 (plausible costs, feasible days).
  - Over budget (run 1: 22 of 52 capped itineraries; run 2: 20). Most are `moderate` itineraries a little over the 200 AUD cap (206–400 AUD per person per day in run 1). The extreme cases are requests that should not have been planned: e049 (`contradictory`, a budget trip with a five-star hotel and a chauffeur, 5,333 AUD per day) and e053 (`prompt_injection`, 3,000 AUD per day). Of the 22 in run 1, 10 are refuse / clarify entries.
  - Out of destination. Most cases come from the knowledge context rather than from the model: the corpus document on Indigenous walking tours lists tours in several states, it is retrieved for these requests, and the generator places them in the requested city — Tower Hill / Worn Gundidj (near Warrnambool) in Melbourne trips (e002, e015, e022, e055) and the Yura Malka Cultural Walk in the Ikara-Flinders Ranges in Adelaide trips (e027, e065). These itineraries are faithful to their context and still leave the destination; `rebuild-rag`'s destination filtering targets this. e046 (London, `out_of_scope`) is outside entirely. e017's only "outside" place is Adelaide, which appears only in a tip about buying supplies before the ferry: a judge error (the one judge-out disagreement in the calibration). Destination prompt v1 does not tell scheduled visits from optional suggestions in tips or from background places, which can lower `destination_rate`.
  - Judge calibration (run 1; 20 itineraries plus 6 checked for destination only, every stratum above the 0.8 minimum). The judge's mistakes were mostly name matches the context does not back: "Freycinet Peninsula" supported because the context mentions "Freycinet oysters" (e062), and stricter readings than a human's on durations and seasons the context does state (e050 "1 hour north to Yanchep", e009 barramundi season). The review rules agreed while scoring are in `docs/evaluation.md` ("Review questions"). Missed claims (10) are a lower bound: only claims a reviewer noticed are recorded.
- **Cost**: 4.5 s per request end to end, 3.2 s of it in the Gemini generation call; $0.00118 per request. A full run takes about 12 minutes with judge concurrency 8.

### rebuild-rag: step-by-step retrieval comparison

> To be filled in after `rebuild-rag` tasks 4.1–4.5 are done. Each step adds only one change, and all runs use the same corpus version (v2) and the same chunking configuration; the chunking comparison gets its own table.

| Configuration | Description | Run ID | Recall@5 | MRR@5 | Retrieval p50 / p95 | Memory usage |
| --- | --- | --- | --- | --- | --- | --- |
| a | Vector-only retrieval (baseline on the new corpus) | `20261104T075807Z-rebuild-rag-a-retrieval` | 0.519 | 0.699 | 633 / 677 ms | not measured |
| b | a + destination filtering | `20261104T081045Z-rebuild-rag-b-retrieval` | 0.609 | 0.782 | 624 / 652 ms | not measured |
| c | b + BM25 hybrid + RRF | `20261104T091258Z-rebuild-rag-c-retrieval` | 0.585 | 0.780 | 656 / 729 ms | not measured |
| c′ | b + Agno `SearchType.hybrid` (control group) | `20261104T091415Z-rebuild-rag-c-agno-retrieval` | 0.609 | 0.782 | 648 / 729 ms | not measured |
| q11 | b + the query chosen in the 12-group comparison | `20261105T070231Z-rebuild-rag-q11-retrieval` | 0.643 | 0.823 | 619 / 669 ms | not measured |
| d | q11 + Cross-Encoder reranking of the vector candidates | `20261105T080155Z-rebuild-rag-d-retrieval` | 0.640 | 0.798 | 905 / 1007 ms | about 890 MB, see step d |
| d′ | q11 + Cross-Encoder reranking of the vector and BM25 candidates | `20261105T080256Z-rebuild-rag-d-fused-retrieval` | 0.632 | 0.798 | 1074 / 1248 ms | about 890 MB, see step d |

**Chunking configuration comparison** (retrieval configuration fixed to the best one chosen in the table above)

| Chunking configuration | Chunk count | Run ID | Recall@5 | MRR@5 |
| --- | --- | --- | --- | --- |
| | | | | |

**Final choice**: — (fill in the configuration and the reasons, and sync it to `openspec/changes/rebuild-rag/design.md`)

---

## Threshold change log

Every modification of `eval/thresholds.yaml` must be recorded here.

| Date | Change | Metric | Old threshold | New threshold | Reason |
| --- | --- | --- | --- | --- | --- |
| 2026-10-26 | `build-evaluation-harness` | `format_pass_rate` (min) | — | 0.9 | Initial setting. Both clean v0.1.0 smoke runs (`20261026T105704Z-v010-baseline-smoke`, `20261026T114334Z-v010-baseline-smoke`) scored 1.0; loosened by one of 10 entries |
| 2026-10-26 | `build-evaluation-harness` | `trip_length_rate` (min) | — | 0.9 | Initial setting. Both smoke runs 1.0; loosened by one of 10 planned itineraries |
| 2026-10-26 | `build-evaluation-harness` | `budget_rate` (min) | — | 0.375 | Initial setting. Both smoke runs 0.5; loosened by one of 8 capped itineraries (0.125) |
| 2026-10-26 | `build-evaluation-harness` | `recall_at_5` (min) | — | 0.809 | Initial setting. Both smoke runs 0.952; loosened by one of 7 labelled entries (1/7 ≈ 0.143) |
| 2026-10-26 | `build-evaluation-harness` | `error_rate` (max) | — | 0.1 | Initial setting. Both smoke runs 0.0; loosened by one of 10 requests |

---

## Dataset change log

Every modification of the evaluation dataset (`eval/dataset.jsonl`) must be recorded here, with the version bumped. In principle the evaluation dataset is written before experiments start and changed as little as possible afterwards, to avoid "changing the exam questions to fit the results".

| Date | Version | What changed | Reason | Entries affected |
| --- | --- | --- | --- | --- |
| 2026-11-04 | v3 | `relevant_sections` of all 60 plan entries relabelled for corpus v2 by page title + section; retired v1 city guides removed from labels; plan entries gain `corpus_coverage`; `corpus_version` set to v2. Requests unchanged | `rebuild-rag` replaces the corpus (task 2.1). Labels name the page because destination + section would merge every district's `Eat` into one label and inflate Recall | e001–e012, e016–e029, e034–e044, e054–e057, e059–e071, e074–e079 |
| 2026-10-31 | v2 | Added e074–e079 (tag `budget_amount`): each is a copy of a v1 plan entry — e074/e004, e075/e024, e076/e022, e077/e001, e078/e003, e079/e029 — with `form.max_daily_budget_aud` (50, 120, 120, 300, 1500, 600) and the amount added to the utterance, so each pair differs only in the amount; e079 keeps e029's `mixed_language` tag and mixed-language utterance. `gold_slots` has no amount field yet (added with a request parser, roadmap item 3). Subsets `dataset-v1` (e001–e073) and `budget-amount` (e074–e079) let runs compare with the v1 baseline and report the new entries separately. No v1 entry changed | `harden-workflow-guardrails` adds `max_daily_budget_aud` (task 6.5); the spec requires entries with an amount for every budget level, a `luxury` one and one above its level's default. Written and reviewed before the final evaluation of the change | e074–e079 (new) |
| 2026-10-25 | v1 | Initial version: 73 entries (54 plan / 12 refuse / 7 clarify), labelled against corpus v1 (the 13 handwritten v0.1.0 documents); 24 entries carry `form.notes` | Written and reviewed entry by entry before any experiment | All (e001–e073) |
