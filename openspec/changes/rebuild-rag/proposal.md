# Proposal

## Why

Today's RAG merely "runs"; there is no way to show it is actually useful. Code review found the following problems:

- The knowledge base has only 13 handwritten documents (4 city guides, 9 Australia-wide topics, about 550 characters on average), each a single paragraph, with no chunking.
- A fixed Top-5 means each query returns about 40% of the knowledge base, so ranking barely matters.
- There is no filtering by destination, so a question about Sydney may retrieve Melbourne content.
- The retrieval query is a fixed concatenation (travel_style + destination + category). The request has no free-text field either, so the user's specific needs never enter the system.
- Retrieval is vector-only, with no keyword retrieval and no reranking.
- Both queries and documents use the `SEMANTIC_SIMILARITY` embedding type rather than the retrieval-specific types.
- Generated itineraries do not cite sources, so neither users nor reviewers can check which suggestions are supported.
- Requests with intent confidence ≥ 0.85 never retrieve at all, and the high-confidence template has no knowledge placeholder. The family and budget requests in the golden tests both take this path — however good retrieval becomes, the generation quality of these requests will not change at all.

**Goal**: build a RAG at realistic scale, where every improvement step is backed by evaluation numbers and sources are cited, and let every request use it.

A complete redesign of routing (LLM request parsing, whether to introduce true CAG) is **not handled in this change**; see roadmap item 3. This change only makes an interim solution: always retrieve.

## What Changes

- **Expand the knowledge base to realistic scale**: use open data whose licence permits it — mainly Wikivoyage (CC BY-SA, attribution required), supplemented by government open data; do not scrape copyrighted travel sites or sites that forbid scraping. The target is several hundred to a thousand-plus text chunks.
- **Data processing pipeline**: clean → split by section (using Wikivoyage's natural See / Do / Eat / Sleep structure, with overly long sections split further) → add metadata (city, state, category, source URL, section) → write into pgvector. The script can be re-run without producing duplicate data.
- **Retrieval upgrades, each step compared with the evaluation harness**:
  - a. Vector-only retrieval (baseline)
  - b. Plus metadata filtering by destination
  - c. BM25 + vector hybrid retrieval
  - d. Plus Cross-Encoder reranking
  Which ranking approach is finally adopted is decided by the evaluation results and recorded in `docs/experiments.md`; the spec only constrains external behaviour (destination filtering, at most 5 results, ordered by relevance, degradation on failure).
- Queries and documents switch to retrieval-specific embedding types, and all documents are re-embedded.
- **Interim routing: every request retrieves.** `retrieval_decision` always routes to `rag_retrieve`, and confidence is reported only as information; the two generation templates distinguished by confidence are merged into one, `itinerary_with_context`, with a knowledge placeholder. **BREAKING**: `rag_retrieve` starts appearing in the event stream of high-confidence requests, and the `retrieval_decision` event no longer contains `threshold`.
- **Source citations**: each day's suggestions in a generated itinerary cite the text chunks they are based on; citations are checked to really exist; the frontend shows source titles and links.
- `POST /generate` gains an optional free-text field `notes`, used in both the retrieval query and the generation prompt.
- Remove the never-used `source_documents` table and `SourceDocument` model.

## Capabilities

### New Capabilities

(None. Evaluation-related requirements are appended to `evaluation-harness`, introduced by `build-evaluation-harness`.)

### Modified Capabilities

- `intent-routing`: remove the confidence-based routing threshold in favour of the interim "always retrieve"; the routing event no longer contains the threshold.
- `knowledge-retrieval`: runs for every request; query construction, destination filtering, ranking (constraining external behaviour only), text chunk fields (adding state, source, section), the corpus pipeline, knowledge-base seed.
- `itinerary-generation`: a single generation template; a missing template is an error; knowledge context carries citation ids; the generation event lists the citable sources; templates support `{notes}`.
- `output-validation`: the output schema adds per-day `sources`; a new citation validity check; the output event carries citation details.
- `travel-workflow`: the request gains the optional field `notes`; in the step order, `rag_retrieve` becomes run every time.
- `evaluation-harness`: adds step-by-step comparison of retrieval configurations and a citation accuracy metric.

## Impact

- Code: `retrieval_service.py`, `knowledge_base.py`, `gemini_embedder.py`, `steps/rag_retrieve.py`, `steps/retrieval_decision.py`, `config.py`, `intake_model.py`, `steps/generate.py`, `output_validator.py`, `steps/validate_output.py`, `scripts/seed.py`, `src/app/static/index.html` (source display, notes input box); new `data/knowledge/`, `scripts/build_corpus.py`
- Tests: the two high-confidence cases in `test_golden.py` assert "no `rag_retrieve`" and must change to assert that retrieval happens and citations are valid; cases related to the threshold and template selection in `test_retrieval_decision.py` and `test_generate.py` need updating
- Database: `ai.travel_docs` must be rebuilt and re-embedded; a new migration drops `source_documents`
- Evaluation: after the corpus changes, the evaluation dataset's `relevant_sections` must be re-labelled for the new corpus and the corpus version bumped to v2; the evaluation database uses one table per corpus and chunking configuration (`travel_docs_v2_<config>`), and `travel_docs_v1` is kept for re-running the baseline
- Dependencies: a BM25 implementation (e.g. `rank-bm25`); the Cross-Encoder needs `sentence-transformers` (which brings in torch)
- **Paid API**: re-embedding several hundred to a thousand-plus chunks, and again for every chunking configuration tried — embeddings must be cached by "text hash + model + task type"
- **Out of scope**: frontend redesign, changing the generation model, a complete routing redesign, streaming output, Graph RAG, multilingual support
- **Dependencies** (must be archived in this order, otherwise this change's deltas cannot be applied):
  - After `build-evaluation-harness`: needs its baseline, metrics, evaluation database and the `evaluation-harness` capability
  - After `harden-workflow-guardrails`: the "Missing template handling" this change removes is the version as modified by harden; the new template depends on harden's "only one active version per key" and "per-person cost" rules
  - After `true-sse-streaming`: the "Routing decision event" this change modifies assumes stdout is no longer used

**Success criteria** (measured with the evaluation harness)

- Retrieval: the Recall@5 and MRR of every step a → b → c → d are written into `docs/experiments.md`; both metrics of the final configuration are higher than the vector-only baseline on **the same new corpus**.
- Generation: faithfulness is higher than the v0.1.0 baseline, with the requests that used to take the high-confidence path (no knowledge context) reported separately; citation validity is 100% (invalid citations are stopped by validation).
- System: reranking adds no more than 1 second of retrieval latency; the golden tests still pass.
