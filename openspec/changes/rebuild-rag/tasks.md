## 1. Corpus pipeline

- [ ] 1.1 Choose 4–6 cities and download the corresponding Wikivoyage pages at **fixed page revisions** (revision ID) into `data/knowledge/raw/` (this directory is not committed to git); add 1–2 government open datasets with clear licences, recording the download date and dataset version; record each source's URL, revision and licence in `data/knowledge/sources.yaml` and `data/knowledge/LICENSE.md`; Verify: after deleting `raw/`, re-download from `sources.yaml` and run `build_corpus.py`; the output is identical to the committed JSONL; every city is in harden's place-name table
- [ ] 1.2 Implement `scripts/build_corpus.py`: clean → split by section (overly long sections split further, chunk size and overlap configurable) → add metadata (`chunk_id` / `destination` / `state` / `topic` / `source` / `section`) → write JSONL; Verify: unit tests cover long-section splitting, overlap and `chunk_id` stability; two runs on the same input produce identical output
- [ ] 1.3 Convert the existing 9 Australia-wide handwritten documents to the same format (`destination="australia"`, `source="handwritten"`); Verify: the JSONL contains these 9 entries
- [ ] 1.4 Implement an embedding cache (text hash + model + task type) stored in `.cache/embeddings/` (already ignored by `.gitignore`); Verify: a second seed makes no new embedding API calls

## 2. Evaluation dataset

- [ ] 2.1 Re-label the evaluation dataset's `relevant_sections` for the new corpus, bump the corpus version to v2, and record it in `docs/experiments.md`; Verify: the evaluation harness's coverage check passes

## 3. Embedding and seed

- [ ] 3.1 `GeminiEmbedder` supports a task type parameter; retrieval and documents use `RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`, intent classification keeps `SEMANTIC_SIMILARITY`; Verify: unit tests assert the task type passed by each caller
- [ ] 3.2 `seed.py` loads the corpus from `data/knowledge/` and writes it into the knowledge-base table named in the configuration; the table is rebuilt when the chunking configuration changes; Verify: two consecutive runs produce no duplicate data; after changing the chunk size and running, the table contains only the new chunks
- [ ] 3.3 Prepare a small fixed corpus for the test database in `tests/fixtures/knowledge/` (select from the generated JSONL the destinations used by the golden and integration tests — at least sydney, melbourne, brisbane and the low-confidence destination chosen in harden 6.1 — plus a few `australia` general documents, keeping the total within a few dozen chunks); `test-db-setup` writes it into the test database's `travel_docs`; Verify: running `test-db-setup` twice in a row, the second run makes no embedding calls; every destination used by golden retrieves at least one chunk
- [ ] 3.4 In the evaluation database, create one table per chunking configuration (`travel_docs_v2_<config>`), leaving `travel_docs_v1` untouched; Verify: re-running the v0.1.0 baseline configuration gives results matching the baseline recorded in the harness (within normal LLM fluctuation)
- [ ] 3.5 Add an Alembic migration that drops `source_documents`, delete the `SourceDocument` model, and remove this table from `count-rows`; update `test_db_schema.py`: add this migration to the migration chain, delete the `SourceDocument` model and column checks, and change the table list ("4 tables") to 3; Verify: `upgrade head` / `downgrade -1` both succeed on the test database; `dev.py test-destructive` passes

## 4. Retrieval (run the evaluation harness after each step)

- [ ] 4.1 First run a, vector-only retrieval, on the new corpus as the baseline; Verify: `docs/experiments.md` has the numbers for a
- [ ] 4.2 b: destination filtering (city + `australia`; cities not in the knowledge base retrieve only `australia`), adding `destination_matched` to the event; Verify: unit tests cover Known city / City not in the knowledge base; run the evaluation and record b
- [ ] 4.3 c: BM25 + vector two-way candidates (Top-20 each) + RRF fusion; also use Agno `SearchType.hybrid` as a control group; Verify: a unit test asserts "a chunk that matches only on keywords can still be selected as a candidate"; run the evaluation and record c and the control group
- [ ] 4.4 d: Cross-Encoder reranking, falling back to the pre-rerank order when model loading or inference fails; Verify: a unit test mocks a reranking failure; run the evaluation and record d along with memory usage
- [ ] 4.5 Compare 2–3 chunk sizes and the embedding types before and after the change, decide the final configuration, and write it into design.md and `docs/experiments.md`; Verify: both Recall@5 and MRR of the final configuration are higher than a; if reranking is used, the added latency is ≤ 1 second
- [ ] 4.6 Text chunks output all fields; query construction includes `notes`; Verify: update `test_rag_retrieve.py`

## 5. Interim routing and a single template

- [ ] 5.1 `retrieval_decision` always routes to `rag_retrieve`; remove `threshold` from the event and delete `RETRIEVAL_CONFIDENCE_THRESHOLD`; Verify: update `test_retrieval_decision.py` to assert that confidence 0.95 also routes to retrieval
- [ ] 5.2 Seed adds the `itinerary_with_context` template (with `{retrieved_context}`, `{notes}`, citation instructions and "AUD per person"); generate always uses it, and the logic for choosing templates by confidence and falling back is removed; Verify: update `test_generate.py` to cover Any confidence / Template table empty
- [ ] 5.3 Update `test_golden.py`: the two former high-confidence cases now assert that `rag_retrieve` appears, `retrieved_context` is non-empty and citations are valid; Verify: on the test database (small fixed corpus), `pytest -m integration tests/test_golden.py` passes completely

## 6. Source citations

- [ ] 6.1 generate numbers the knowledge chunks `[S1]`… and adds `context_sources` to the event; Verify: `test_generate.py` covers Citation ids assigned / Retrieval returned nothing / Sources listed / No chunks retrieved
- [ ] 6.2 `ItineraryOutput` adds `sources` to each day (harden's `response_schema` is updated along with it); Verify: schema tests cover Day without sources
- [ ] 6.3 validate_output adds a citation validity rule, and on success the event carries `citations`; Verify: unit tests cover Invented citation / Citation without context / Citations resolved
- [ ] 6.4 Frontend: show source titles and links under each day's card, with the Wikivoyage licence notice; Verify: run the Family trip preset once in the browser; the sources are visible and can be opened

## 7. API

- [ ] 7.1 `TravelRequest` gains a `notes` field (leading/trailing whitespace stripped, at most 500 characters, null when blank), and the frontend adds an optional input box; Verify: `test_intake.py` adds Blank notes / Notes too long; manually submit a request with notes and see it in `query_text` in the rag_retrieve panel; harden's injection guardrail applies to `notes` as well

## 8. Evaluation and regression

- [ ] 8.1 Run a full evaluation of the final configuration with the evaluation harness (including citation accuracy), compare against the v0.1.0 baseline, list the changes in faithfulness, latency and cost separately for the former high-confidence requests, and write it into `docs/experiments.md`; update gate thresholds as needed and record the reason; Verify: the success criteria in the proposal are met
- [ ] 8.2 `dev.py test-all` passes completely; the gate passes; `openspec validate rebuild-rag --strict` passes
