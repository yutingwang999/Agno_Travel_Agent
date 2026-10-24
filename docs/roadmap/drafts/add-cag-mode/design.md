# Design

## Context

- After `rebuild-rag`, every chunk in the knowledge base carries lowercase `destination` metadata, and retrieval first filters by `destination IN (city, 'australia')`. Estimate: 50–100 chunks per city, plus the Australia-wide general documents, comes to roughly 10,000–60,000 tokens after filtering, within Gemini's context window.
- After `true-sse-streaming`, `retrieval_decision` is a plain Step, and the Condition only reads its output.
- There are currently two generation templates: `high_confidence_minimal_context` (no knowledge placeholder) and `low_confidence_with_retrieval`.

## Goals / Non-Goals

**Goals:**
- Every generation carries destination knowledge; the basis for routing decisions can be explained and measured.
- Intent classification is responsible only for what it is actually good at: determining the itinerary category, tone and constraints.

**Non-Goals:**
- No calibration of intent classification confidence (it no longer affects routing; the only consequence is that the tone or category may be less accurate, to be handled later).
- No KV-cache-level optimisation of self-hosted models; only the context caching provided by the Gemini API is used.

## Decisions

1. **Routing is based on token count, not confidence.**
   When the filtered knowledge token count ≤ `KNOWLEDGE_TOKEN_BUDGET`, take CAG; otherwise take RAG. The token count is computed with Gemini's `count_tokens` and cached by `(destination, corpus version)`; it can also be estimated first as "character count / 4", with the difference between the two recorded in the experiments.
   Alternatives: (a) always CAG — no way out when the knowledge base grows; (b) always RAG — wastes recall on a small knowledge base; (c) keep using confidence — already shown to be unrelated to the need for knowledge.

2. **The default budget is determined by experiment.** Sweep several budget values on the evaluation dataset (e.g. 8k / 16k / 32k / 64k), observe `expected_facts` coverage, the proportion of unsupported claims, latency and cost, and choose the inflection point. Before the experiment, use a conservative value as a placeholder.

3. **The assembly order of the CAG context is fixed.** City chunks first, then `australia` chunks; within each group, ordered by `source`, `section`. Only with a fixed order can the cache hit and the experiments be reproduced. The format is the same as RAG's retrieval results (`[title]\nchunk_text`), so generate does not need to distinguish the two modes.

4. **Merge the templates into `itinerary_with_knowledge`, renaming the variable `{retrieved_context}` to `{knowledge_context}`.** Both modes provide "knowledge context"; only the source differs. The two old templates are set to `is_active=false` in seed and kept, to reproduce old results via `template_version`.

5. **Context caching is an optimisation, not a prerequisite for correctness.** A cache is created only when the context reaches the minimum token count for Gemini's explicit caching, with cache key `(destination, corpus version, template version)` and a TTL; when creating or using the cache fails, the context is inlined directly into the prompt. Events and traces record `context_cached`.

6. **`cag_match` → `intent_match`, done in one go as a BREAKING change.** The frontend, tests and docs are changed at the same time. Alternative: keep the old step name — then a true CAG step and a step called "cag" that is not CAG would exist side by side, which costs more than renaming.

7. **Generation-level evaluation uses LLM scoring.** For each query, a scoring model judges which `expected_facts` the generated itinerary covers and which claims have no support in the knowledge context. The scoring model is configured separately from the generation model; a sample is checked manually, and the agreement rate between the scoring model and human judgement is recorded.

## Risks / Trade-offs

- [The longer the context, the more easily the model ignores content in the middle (lost in the middle)] → This is exactly why the token budget exists; the budget is determined by experiment.
- [CAG uses more input tokens per request and costs more] → Context caching gives a discount; the experiment report records the cost per request.
- [Explicit caching has a minimum token count and is billed by storage duration] → Inline below the minimum; set a TTL; the specific numbers follow the Gemini documentation and are not written into the spec.
- [LLM scoring is itself biased] → Manual sample checks, with the agreement rate reported.
- [The BREAKING step rename affects clients that depend on SSE] → The only client today is the bundled frontend, which is changed at the same time; noted in the CHANGELOG.

## Migration Plan

1. Seed adds `itinerary_with_knowledge` (active), and the two old templates become inactive.
2. Deploy the code (step rename, new routing, `cag_context`).
3. Rollback: restore the previous code version and set the two old templates active again.

## Open Questions

- Whether the token count is computed exactly with `count_tokens` or estimated from character count — does not affect the spec (the spec only requires comparing with the budget); decided by the error seen in the experiments.
