# Roadmap

The improvement plan after v0.1.0. **Near-term** work has already been written up as OpenSpec changes in `openspec/changes/`; **later** work is recorded here first, and a change is created when work is about to start, written against the main specs at that time.

Every improvement must be measured with the evaluation harness (`build-evaluation-harness`), with a before/after comparison reported in `docs/experiments.md`.

## Near term: changes already created

Listed in order of completion (archiving). The order cannot be changed freely: the deltas of later changes are written against the main specs as they will be after the earlier changes are archived.

| Order | Change | Content | Must be archived after |
| --- | --- | --- | --- |
| 1 | `isolate-test-database` | Tests use a separate test database and no longer wipe the development database | — |
| 2 | `build-evaluation-harness` | Evaluation dataset (50–100 entries), evaluation database, metrics for four stages, comparison reports, regression gate; run the v0.1.0 baseline | 1 |
| 3 | `harden-workflow-guardrails` | Error handling, native structured output, business rule checks (per-person costs), input guardrails (including Chinese place names), template version management | 2 |
| 4 | `true-sse-streaming` | Push each step as it completes, don't block the event loop, remove stdout capture | No dependency on 2 or 3, but must come before 5 |
| 5 | `rebuild-rag` | Realistic-scale open-data knowledge base, step-by-step retrieval improvements a→d, source citations, interim routing (always retrieve) | 2, 3, 4 |

**Gate thresholds**: intentional behaviour changes (e.g. 3 starting to refuse out-of-scope requests, 5 making every request retrieve) may lower some metrics. In that case, update `eval/thresholds.yaml` in the same change and state the reason in the "Threshold change log" of `docs/experiments.md`.

## Later: changes not yet created

### 3. Drop "CAG" in favour of real routing

- **Problem**: the name is inaccurate (the project's "CAG" is really embedding-based intent classification, not Cache-Augmented Generation); the 0.85 threshold has no justification; using "intent classification confidence" to decide "whether to retrieve" makes no logical sense. The high-confidence template does not even have a knowledge placeholder, so the clearer the intent, the less destination knowledge it gets.
- **Current state**: `rebuild-rag` makes an interim solution — always retrieve, confidence is reported but takes no part in routing, and the generation templates are merged into one. The `retrieval_decision` step is kept as the plug-in point for the new routing.
- **Direction**: use LLM structured output to parse what the user says into a request object (destination, trip length, budget, preferences, whether specific place information is needed), and let the parse result plus rules decide which path to take; ask the user back when key information is missing.
- **Comparison**: keep the embedding classification as a baseline, compare the two on the evaluation dataset for slot accuracy, latency and cost, choose one and state why. The evaluation dataset already includes `utterance` and `gold_slots`.
- **⚠️ To be decided**: whether to also build **true CAG** (choosing between "put the whole destination knowledge into the context" and RAG by token budget). The draft is in [`drafts/add-cag-mode/`](roadmap/drafts/add-cag-mode/). The two can be combined: LLM parsing decides "whether knowledge is needed", and the token budget decides "CAG or RAG". The draft was written against the old plan (it references the cancelled `knowledge-evaluation`) and must be rewritten when the change is formally created.
- **Side note**: asking the user back requires sessions, so design it together with item 5.

### 4. Tool calling (real agent capability)

- 2–3 genuinely useful tools: weather (Open-Meteo, free, no key needed), places and distances (OpenStreetMap / Nominatim, respecting the usage policy and rate limits), a budget calculator (computed by deterministic code, not letting the model do the addition).
- The main flow stays fixed; only in the "planning" step does the model decide which tools to call; limit the number of calls and the total time.
- After Nominatim is integrated, change "attractions really are in the destination" from a judge-model decision to a **code check** (`harden-workflow-guardrails` does not yet implement a runtime check); the place-name table in the input guardrails can also switch to Nominatim.

### 5. Multi-turn itinerary revision (decided to do)

- Users can say things like "make day two cheaper" or "change it to suit kids".
- **Design principle**: the itinerary object is the core, and the conversation is just revision instructions. State = the current itinerary (structured, versioned) + user constraints; each turn gives the model "the current itinerary + this instruction" rather than the whole chat history, so the context does not grow with the number of turns; only the affected days are regenerated, and after merging the whole itinerary goes through the business rule validation again.
- **Needs**: a session table and an itinerary version table (v0.1.0 does not store generated itineraries in the database at all); the API becomes session-centred; a chat box in the frontend.
- **Metrics**: revision success rate, preservation rate of unchanged parts, constraint preservation rate, per-turn cost and latency (compared with regenerating the whole itinerary). The evaluation dataset needs multi-turn cases (initial request + 2–3 rounds of revision instructions + the expected result for each round).
- **Reserved for it**: the `notes` field added in `rebuild-rag` will evolve into free-text messages in a session; when designing the new interface, include `session_id` in requests.
- Recommended after item 3, or together with item 3, since both need sessions.

### 7. Swappable models, with comparison

- A very thin provider wrapper (Gemini primarily, switchable to another provider).
- Compare 2 models on the evaluation dataset for quality, latency and cost per request; the README states clearly "which models were tested and when", to avoid outdated version numbers.

### 8. Deployment and CI/CD

- Write a Dockerfile for the app and deploy to Cloud Run or Render; use managed Postgres + pgvector for the database (e.g. Neon or Supabase).
- GitHub Actions: code checks → unit tests → evaluation smoke subset (`build-evaluation-harness` already provides the gate command); CI fails when a metric is below its threshold.
- Protection for the online demo: request rate limiting, a daily call cap, API keys kept server-side only.
- **Limit what SSE events expose in the public demo.** Since v0.1.0 every step event carries its internals to the frontend: `generate` sends `raw_llm_output` and the prompt template key / version, `rag_retrieve` the query text and the retrieved chunks, `cag_match` the category, confidence, tone and constraints that go into the prompt, and a failed `validate_output` the Pydantic error details. Add a "public" mode whose events carry only step name, status and the final itinerary, with the internals kept in traces and logs, and keep today's full events as a "debug" mode. This is a public API and UI change and needs its own decision on which fields each mode keeps.
- **Note the conflict with `rebuild-rag`**: if the final configuration uses a local Cross-Encoder, torch plus the model needs several hundred MB to over 1GB of memory, which very likely does not fit in the free tiers. At that point choose between "smaller model / hosted reranking service / no reranking", justifying the trade-off with evaluation numbers.
- Put the demo link and a GIF at the top of the README.

### 9. Observability upgrade

- Token usage is already written to traces in `build-evaluation-harness`; later add cost and tool-call records.
- Optional: integrate Langfuse or OpenTelemetry.
- A simple stats page: request volume, average cost, failure rate.

### 10. Chinese–English bilingual support (optional)

- Support asking in Chinese and outputting itineraries in Chinese; the evaluation dataset already has `mixed_language` entries.
- The embedding needs to switch to a multilingual model (or the multilingual performance of gemini-embedding-001 needs to be verified); switching models means re-embedding all content.
- The place-name table in `harden-workflow-guardrails` already contains the Chinese names of the major cities; full bilingual support would need to expand it and handle Chinese travel_style and notes.

## Other small items

- Calibrating intent classification confidence (e.g. using the top-1 vs top-2 margin instead of the raw cosine value) — see whether it is still needed after item 3 is decided.
- Cancel the running workflow after the client disconnects (from the Open Questions of `true-sse-streaming`).
- Whether generated itineraries should show finer-grained sources (currently cited per day).
