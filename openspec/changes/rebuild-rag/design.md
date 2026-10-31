# Design

## Context

- Retrieval is implemented with Agno `Knowledge` + `PgVector` (table `ai.travel_docs`, `SearchType.vector`, cosine distance); seed writes documents with `Knowledge.insert()`.
- In the installed Agno 2.5.14, `PgVector` supports `SearchType.hybrid`, `search(filters=...)` and a `reranker` parameter. But its keyword part is Postgres full-text search (`ts_rank`), not BM25, and its fusion is not RRF.
- `GeminiEmbedder` is shared by seed and retrieval and currently always uses `SEMANTIC_SIMILARITY`; intent classification (cag_match) also uses this type, and 50 category vectors depend on it.
- intake lowercases destination (`sydney`), while the existing documents' metadata is capitalised (`Sydney`); 9 of the 13 documents have destination `Australia`.
- `build-evaluation-harness` provides the evaluation dataset, metrics such as Recall@k / MRR and faithfulness, and the run and comparison commands.

## Goals / Non-Goals

**Goals:**
- Every design choice can be justified with numbers on the evaluation dataset.
- Users can see which material each day's suggestions are based on.

**Non-Goals:**
- No tuning of the generation prompt (only adding `{notes}` and citation instructions).
- No online A/B testing, no Cross-Encoder fine-tuning (see how it does without fine-tuning first).

## Decisions

| Decision | Approach | Alternatives / points decided by experiment |
| --- | --- | --- |
| Data sources | Mainly **Wikivoyage** (CC BY-SA): organised by city in sections, a natural fit for section-based splitting; keep the source URL and give attribution. **Government open data** as a supplement (e.g. attraction data with clear licences from state tourism bodies or government open-data portals), with each dataset's licence recorded separately. Target several hundred to a thousand-plus chunks, covering 4–6 cities first | Official tourism websites: the content is copyrighted and the terms of use generally do not allow scraping and republishing, so they are not used. The existing 9 Australia-wide handwritten documents are kept as `australia` general documents |
| Pipeline | `scripts/build_corpus.py`: download → clean (remove navigation, templates, coordinate markers) → split by section → add metadata → write JSONL to `data/knowledge/`; `seed.py` only writes the JSONL into pgvector. The two steps are separate, so changing the chunking does not require re-downloading | — |
| Chunking | Split by section; overly long sections are split further by paragraph and finally by fixed length, with a small overlap | Compare 2–3 options each for chunk size and overlap |
| Metadata | `destination` (city, always lowercase), `state` (state), `topic` (category: food / nature / culture…), `source` (URL; `handwritten` for handwritten documents), `section` (section title), `chunk_id` (stable ID: hash of source + section + sequence number) | — |
| Embedding cache | Cache locally by "text hash + model + task type", so comparing several chunking configurations does not repeat paid API calls | — |
| Destination filtering | `destination IN (requested destination, 'australia')`; cities not in the knowledge base retrieve only `australia` | Filtering strictly by city would mean the Australia-wide documents are never retrieved, so it is not used |
| Embedding | gemini-embedding-001; queries use `RETRIEVAL_QUERY`, documents use `RETRIEVAL_DOCUMENT`. `GeminiEmbedder` gains a task type parameter; **intent classification keeps using `SEMANTIC_SIMILARITY`**, so the 50 categories do not need re-embedding | Compare the effect before and after the change |
| Retrieval | Two paths, keyword + vector, Top-20 candidates each | (a) Our own BM25 (e.g. `rank-bm25`; a thousand-plus chunks fit in memory) + RRF; (b) Agno's `SearchType.hybrid`. Both go into the evaluation comparison, and the numbers decide |
| Fusion | RRF (reciprocal rank fusion) | Alternative: take the union of both paths directly and hand it to reranking |
| Reranking | A Cross-Encoder (e.g. the MiniLM family) reranks the candidates, keeping Top-5 | Whether fine-tuning is needed: see how it does without fine-tuning first |
| Query construction | `notes` (if any) + travel_style + destination + matched category | Compare with the current fixed concatenated query |
| Step-by-step comparison | Run in order a vector-only → b + destination filtering → c + BM25 hybrid → d + reranking, running the evaluation harness at each step and recording Recall@5, MRR and latency | Each step changes only one variable, so improvements can be attributed |

### Interim routing: always retrieve

1. **`retrieval_decision` always routes to `rag_retrieve`; the step itself is kept.** Confidence is still reported but no longer affects routing; `RETRIEVAL_CONFIDENCE_THRESHOLD` is deleted. The step is kept so that the new routing in roadmap item 3 has a place to plug in, and to avoid changing the step name and event structure a second time.
   Alternatives: (a) keep the status quo — retrieval improvements would not reach high-confidence requests, and the success criteria could not be met; (b) do the complete routing redesign now — too large in scope, and it still has undecided questions (see roadmap item 3).
2. **The two generation templates merge into `itinerary_with_context`**, containing `{retrieved_context}`, `{notes}`, citation instructions, and the "AUD per person, excluding accommodation" wording and the `{daily_budget_ceiling}` placeholder that harden requires. The two old keys remain in the database (under harden's rules, the version declared in `ACTIVE_TEMPLATE_VERSIONS` stays active but is no longer selected), so earlier results can be reproduced with `template_version`.

3. **How the merged template describes the request is decided by comparison, not fixed in advance.** In v0.1.0 the user's own words never reach the generator: the templates have no `{travel_style}` placeholder, so "seniors, slow pace" reaches Gemini only as the matched category `senior` plus that category's preset tone and constraints ("step-free stays, accessible transport"), which then fill the itinerary with wheelchair and lift advice nobody asked for (baseline e039). With confidence often near the old threshold (0.81–0.86), a wrong category also brings wrong constraints. Three variants of `itinerary_with_context` are compared on the evaluation dataset, differing only in this part:

   | Variant | Request description in the template |
   | --- | --- |
   | A | Matched category with its preset tone and constraints (as in v0.1.0) |
   | B | The user's `{travel_style}` and `{notes}` only, no preset |
   | C | Both, stating that the user's words take precedence and the preset is a default suggestion |

   The existing metrics cannot tell these apart (none asks whether the itinerary fits what the user asked for), so the comparison needs a new judge metric, preference adherence (task 2.4). The winner is the seeded version of `itinerary_with_context`; the decision and its numbers go into this section and `docs/experiments.md`. Whether the category presets survive at all after roadmap item 3 (request parsing) is decided there, starting from this result.

4. **Candidate template instruction, not in the first version of `itinerary_with_context`: "do not invent exclusive or private arrangements unless the context offers them".** The v0.1.0 baseline's luxury itineraries are full of private viewings, after-hours access and charters that no corpus can confirm can be booked (e065: "a private look at the Dali exhibition" at d'Arenberg). It is tested as its own change to the template after decision 3 is settled, so that each comparison changes one thing, and measured with the `activity` kind of faithfulness v2 (task 2.3).

### The spec constrains only external behaviour

The fusion method (RRF / union), whether to use Agno hybrid, and whether to rerank are all to be decided by experiment. So the spec only states externally observable behaviour: filtering by destination, at most 5 results, ordered by relevance, degradation on failure, and it requires the final configuration and its evaluation results to be recorded in `docs/experiments.md`. The approaches in the table above are starting points for experiments, not commitments.

### Evaluation environment

The evaluation database uses one knowledge-base table per corpus and chunking configuration (e.g. `travel_docs_v2_c300`, `travel_docs_v2_c500`), and `travel_docs_v1` is kept untouched. The development database keeps only the finally chosen one (table name still `travel_docs`). This way the a→d step-by-step comparison and the chunking comparison can run side by side at the same time, and the v0.1.0 baseline can be re-run at any time.

The three databases each have a different corpus:

| Database | Corpus | Purpose |
| --- | --- | --- |
| Evaluation database | Full; one table per corpus / chunking configuration, kept long term | All numbers in `docs/experiments.md` |
| Development database | The finally chosen configuration (`travel_docs`) | Day-to-day manual use |
| Test database | **Small fixed corpus** `tests/fixtures/knowledge/` (a few dozen chunks, covering the destinations used by the golden and integration tests + a few `australia` documents) | Functional correctness: flow, branches, structure, valid citations |

The test database is wiped and re-seeded by the destructive tests, so a full corpus would mean re-embedding a thousand-plus chunks every time; and the golden tests only check structure and branches, not retrieval quality, so a small corpus is enough. Retrieval quality is measured only by evaluations on the evaluation database, so using a subset in the test database does not affect the experimental comparisons.
Alternative: the full corpus in the test database too, plus the embedding cache — the cache avoids paying repeatedly, but seeding still takes a long time, and test results would vary as the corpus changes.

### Source citations

1. **Give each text chunk a citation id scoped to the current request.** When generate assembles the knowledge context, it numbers the chunks in order `S1`, `S2`…, formatted as `[S1] title\nbody`; `context_sources` in the generation event lists each id's `chunk_id`, title, source URL and section.
   Alternative: have the model cite `chunk_id` directly — the IDs are long and the model easily miscopies them; short ids are more reliable.
2. **The output schema adds `sources: list[str]` to each day**, holding the ids that day's suggestions are based on. The template states: only cite ids that appear in the context; leave it empty when there is no support.
3. **Citation validity is checked by code**: every id must appear in `context_sources`, otherwise it counts as a validation failure and enters corrective retry. When retrieval returned no chunks, `sources` must be empty.
4. **Whether a citation really supports the content is measured by the evaluation harness's judge model** (citation accuracy), not checked at runtime.
5. **Frontend**: under each day's card, list the titles and links of the cited sources; Wikivoyage sources carry the licence notice.

## Risks / Trade-offs

- [`sentence-transformers` brings in torch; the dependency is several hundred MB and CPU inference adds latency] → Load the reranking model once at process start; the success criteria set a latency cap; if it is exceeded, fall back to "fusion without reranking" or switch to a smaller model.
- [Wikivoyage is CC BY-SA, requiring attribution and share-alike] → Every chunk stores `source`; the frontend shows sources; the README and `data/knowledge/` state the licence.
- [Government open-data licences vary] → Record each dataset's source and licence separately; datasets with unclear licences are not used.
- [The cost of re-embedding a thousand-plus chunks] → Embedding cache; seed stays idempotent; tables are rebuilt only when the chunking configuration changes.
- [The model may fill in citation ids arbitrarily] → The validity check stops ids that do not exist; citation accuracy is measured by the evaluation.
- [The reranking model fails to download or inference errors] → Fall back to the pre-rerank order (see Reranking failure fallback in the spec).
- [A local Cross-Encoder conflicts with roadmap item 8 (deployment): torch plus the model needs several hundred MB to over 1GB of memory, which very likely does not fit in the free tiers of Cloud Run / Render] → Record memory usage in the experiment report; at deployment time, choose between "smaller model / hosted reranking service / no reranking", justifying the trade-off with evaluation numbers.
- [Always retrieving adds one embedding call and retrieval latency to the former high-confidence requests] → List the latency and cost changes of these requests separately in the evaluation report.
- [The new corpus requires re-labelling the evaluation dataset, which is a lot of work] → Label down to "source + section"; how many chunks a section is split into does not affect the labels.

## Migration Plan

1. New Alembic migration: drop the `source_documents` table; delete the `SourceDocument` model and remove this table from `count-rows`.
2. Generate the new corpus and write it into `travel_docs_v2_<config>` in the evaluation database, one per chunking configuration; once the experiments choose a configuration, drop `ai.travel_docs` on the development database and rebuild it with the chosen configuration (documents now embedded with `RETRIEVAL_DOCUMENT`).
3. Label the evaluation dataset for the new corpus and bump the corpus version to v2.
4. Seed adds the `itinerary_with_context` template (with `{notes}`, `{retrieved_context}`, `{daily_budget_ceiling}`, citation instructions and "AUD per person, excluding accommodation"); the two old generation templates are kept.
5. Deploy the code (always retrieve, single template, source citations).
6. Rollback: the migration's downgrade recreates an empty `source_documents` table; the knowledge base is rebuilt with the old seed; restoring the previous code version returns to choosing templates by confidence (the old templates are still in the database).
