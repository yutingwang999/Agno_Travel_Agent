## 1. Rename: cag_match → intent_match (BREAKING)

- [ ] 1.1 Change `cag_match` to `intent_match` in steps, files, functions and tests; Verify: `grep -ri cag_match src tests` returns nothing, and the unit tests pass
- [ ] 1.2 Change the step name in the frontend `index.html` accordingly; Verify: run it once in the browser and every step panel displays correctly
- [ ] 1.3 Edit the Purpose of the main spec `openspec/specs/intent-routing/spec.md` directly, removing the "CAG side" wording in favour of intent classification; Verify: code review

## 2. Knowledge mode decision

- [ ] 2.1 Implement selection of the eligible chunks (reusing rebuild-rag's destination filtering) and token counting (cached by `(destination, corpus version)`); Verify: unit tests cover a known city and a city not in the knowledge base
- [ ] 2.2 Change `retrieval_decision` to choose the mode by `KNOWLEDGE_TOKEN_BUDGET`, emitting `knowledge_mode` / `knowledge_tokens` / `token_budget` / `destination_matched`; delete `RETRIEVAL_CONFIDENCE_THRESHOLD`; Verify: write unit tests for the three scenarios Small / Large destination corpus and Confidence is ignored
- [ ] 2.3 Change the workflow's Condition to choose between `cag_context` and `rag_retrieve`; Verify: `test_workflow_skeleton.py` covers the step order in both modes

## 3. CAG context

- [ ] 3.1 Implement the `cag_context` step, emitting all eligible chunks in a fixed order; Verify: a unit test asserts Stable order
- [ ] 3.2 generate supports Gemini context caching, inlining when below the minimum token count or on error; record `context_cached`; Verify: a unit test mocks a cache creation failure and asserts that generation continues and `context_cached=false`

## 4. Templates

- [ ] 4.1 Seed adds `itinerary_with_knowledge` (with `{knowledge_context}` and `{notes}`), and the two old templates become inactive (existing databases need a one-off update script); Verify: `count-rows` plus a SQL query shows only one active generation template
- [ ] 4.2 generate always uses the new template, and the logic for choosing templates by confidence and falling back is removed; `{retrieved_context}` becomes `{knowledge_context}`; add `knowledge_mode` to the generation event; Verify: update `test_generate.py`

## 5. Evaluation

- [ ] 5.1 Implement `scripts/eval_generation.py` (LLM scoring of fact coverage and unsupported claims, with the scoring model configured separately); Verify: run it end to end on 2 queries and produce a report
- [ ] 5.2 Manually label ≥ 20 samples and compute the agreement rate between the scoring model and human judgement; Verify: the number is written into `docs/experiments.md`
- [ ] 5.3 Run the comparison of the four approaches (vector-only RAG / hybrid RAG / forced CAG / budget-based routing); Verify: all four rows are in the report
- [ ] 5.4 Sweep ≥ 4 token budget values, choose the default and write it into `config.py` and `docs/experiments.md`; Verify: the report has one row of data per budget

## 6. Docs and regression

- [ ] 6.1 Rewrite DESIGN.md sections 2 and 8 (the CAG / RAG boundary), and update the README, `docs/api.md` and the CHANGELOG (noting BREAKING); Verify: a full-text search for "CAG" shows every occurrence refers to true Cache-Augmented Generation
- [ ] 6.2 Update the golden tests: the high-confidence path no longer asserts "no retrieval" but instead asserts that both modes carry knowledge context; Verify: `python -m pytest tests/ -v` passes completely
- [ ] 6.3 `openspec validate add-cag-mode --strict` passes
