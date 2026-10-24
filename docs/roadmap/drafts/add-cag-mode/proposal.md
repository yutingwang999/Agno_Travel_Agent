# Proposal

## Why

Today's routing uses the intent classification confidence (how similar the request is to the closest of the 50 itinerary categories) to decide whether to retrieve. But this score has nothing to do with "whether destination knowledge is needed", and the 0.85 threshold has no experimental basis; worse, the high-confidence template has no `{retrieved_context}`, so the clearer the intent, the less the LLM gets any destination facts at all. In addition, the step the project calls "CAG" is really embedding-based intent classification, which is not the same thing as CAG in the industry sense (Cache-Augmented Generation: putting the whole knowledge base into the LLM context up front and using caching to skip retrieval), and it easily misleads readers.

Even after `rebuild-rag`, our knowledge base has only a few hundred chunks; filtered by destination it fits entirely into Gemini's context window, which makes it a good fit for true CAG.

## What Changes

- Add a true CAG mode: put all the knowledge filtered by destination into the generation context; use Gemini's context caching when the conditions are met.
- The routing basis changes from "intent confidence" to "**amount of knowledge**": filtered knowledge token count ≤ budget → CAG; over budget → RAG. The budget is configurable, with the default determined by evaluation experiments.
- Every generation carries destination knowledge; the two generation templates distinguished by confidence are merged into one, `itinerary_with_knowledge`.
- **BREAKING**: the step `cag_match` is renamed to `intent_match` (affecting `step` / `step_name` in SSE events and traces); the `data` field of the `retrieval_decision` event changes; a new step `cag_context` is added.
- In the documentation, the term "CAG" is used only for true CAG; the original step is uniformly called intent classification.
- Evaluation: on top of `rebuild-rag`'s evaluation framework, add generation-level evaluation comparing three approaches — vector-only RAG, hybrid RAG and CAG — and determine the token budget by experiment.

## Capabilities

### New Capabilities

- `knowledge-context`: knowledge mode decision (CAG / RAG), CAG context assembly, context caching and its failure fallback.

### Modified Capabilities

- `intent-routing`: the step is renamed to `intent_match`; the confidence-based routing requirements and routing event are removed (moved to `knowledge-context`). The "CAG" wording in the Purpose section requires editing the main spec directly.
- `knowledge-retrieval`: runs only when the knowledge mode is RAG.
- `itinerary-generation`: template selection, missing-template handling, knowledge context format, seeded templates, generation event fields.
- `travel-workflow`: step order, event order, step names in traces.
- `knowledge-evaluation`: add generation-level evaluation and token budget calibration.

## Impact

- Code: `travel_workflow.py`, `steps/cag_match.py` (renamed to `steps/intent_match.py`), `steps/retrieval_decision.py`, new `steps/cag_context.py`, `steps/generate.py`, `config.py`, `scripts/seed.py`, `src/app/static/index.html` (step names)
- Docs: `DESIGN.md` (the CAG / RAG boundary in sections 2 and 8 needs rewriting), `README.md`, `docs/api.md`
- Tests: the golden tests (the assertion that the high-confidence path has "no rag_retrieve" no longer holds), every test that references `cag_match`
- Dependencies: the Gemini context caching API; the cost model changes (CAG uses more input tokens per request, but with a caching discount)
- **Dependencies**: must come after `rebuild-rag` (needs its destination metadata, filtering rules and evaluation framework), and after `true-sse-streaming` (the routing event assumes stdout is no longer used). It is also recommended to come after `harden-workflow-errors`; this change's deltas are written against the specs after all three are complete.

**Success criteria**

- On the evaluation dataset, the final routing approach is no lower in `expected_facts` coverage than the best of the three single approaches, and its proportion of unsupported claims is not higher; the numbers are written into `docs/experiments.md`.
- The default token budget is backed by experimental data.
