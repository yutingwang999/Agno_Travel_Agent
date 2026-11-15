# Roadmap

The improvement plan after v0.1.0. Work that is about to start is written up as an OpenSpec change in `openspec/changes/`, against the main specs at that time; **later** work is recorded here first.

Every improvement must be measured with the evaluation harness (`build-evaluation-harness`), with a before/after comparison reported in `docs/experiments.md`.

**Gate thresholds**: an intentional behaviour change may lower some metrics (as `harden-workflow-guardrails` did by refusing out-of-scope requests, and `rebuild-rag` by making every request retrieve). In that case, update `eval/thresholds.yaml` in the same change and state the reason in the "Threshold change log" of `docs/experiments.md`.

## Done: the first five changes

Completed and archived in this order (`openspec/changes/archive/`); each later change's deltas were written against the main specs as they were after the earlier ones were archived. What each one shipped is in `CHANGELOG.md`, and its measured results in `docs/experiments.md`.

| Order | Change | Content | Archived |
| --- | --- | --- | --- |
| 1 | `isolate-test-database` | Tests use a separate test database and no longer wipe the development database | 2026-10-24 |
| 2 | `build-evaluation-harness` | Evaluation dataset, evaluation database, metrics for four stages, comparison reports, regression gate; the v0.1.0 baseline | 2026-10-28 |
| 3 | `harden-workflow-guardrails` | Error handling, native structured output, business rule checks (per-person costs), input guardrails (including Chinese place names), template version management | 2026-10-31 |
| 4 | `true-sse-streaming` | Push each step as it completes, don't block the event loop, remove stdout capture | 2026-11-01 |
| 5 | `rebuild-rag` | Wikivoyage knowledge base, retrieval comparisons (vector + destination filter adopted; hybrid and reranking not), source citations, interim routing (always retrieve) | 2026-11-10 |

## Next: item 3 in two changes

To be archived in this order; the deltas of 7 are written against the main specs as they will be after 6 is archived.

| Order | Change | Content | Status |
| --- | --- | --- | --- |
| 6 | `parse-requests` | `POST /parse` turns one free-text sentence into the form's fields, with defaults and `assumptions`; the guards and `not_a_travel_request` at parse time; a "Describe your trip" way in that fills the form; the free-text path in the evaluation (slot accuracy, field agreement, parser latency and cost) | Created |
| 7 | `clarify-requests` | Clarifying questions for contradictory or unfeasible requests (see item 3) | Not created yet; planned after 6 is archived |

## Later: changes not yet created

### 3. Drop "CAG" in favour of real routing

- **Problem**: the name is inaccurate (the project's "CAG" is really embedding-based intent classification, not Cache-Augmented Generation); the 0.85 threshold has no justification; using "intent classification confidence" to decide "whether to retrieve" makes no logical sense. The high-confidence template does not even have a knowledge placeholder, so the clearer the intent, the less destination knowledge it gets.
- **Current state**: `rebuild-rag` made an interim solution — always retrieve, confidence is reported but takes no part in routing, and the generation templates are merged into one. The `retrieval_decision` step is kept as the plug-in point for the new routing.
- **Direction**: use LLM structured output to parse what the user says into a request object (destination, trip length, budget, preferences, whether specific place information is needed), and let the parse result plus rules decide which path to take; ask the user back when key information is missing.
- **Split into two changes** (order 6 and 7 above):
  - **`parse-requests`** (created): the parser and a free-text way in. Free text fills the form, the user reviews it, and `/generate` stays unchanged. A missing destination or trip length is left empty for the user to fill in; that is the only asking back this change does. Routing and `cag_match` are unchanged.
  - **`clarify-requests`** (not created yet): clarifying questions for requests that parse completely but are contradictory or unfeasible (e.g. "drive the whole coast from Perth to Darwin" in two days, e050; a daily amount below what the destination plausibly costs, see item 4). Decisions so far: **one round** of questions, each offered **with choices** for the user to pick from, and a **fallback rule** for what happens when the request is still not plannable after that round (the rule itself is decided when the change is created). The evaluation observes these questions as `clarify`, so the contradictory `clarify` entries, which still fail after `parse-requests`, can count as correct.
- **Comparison**: keep the embedding classification as a baseline, compare the two on the evaluation dataset for slot accuracy, latency and cost, choose one and state why. The evaluation dataset already includes `utterance` and `gold_slots`. `parse-requests` measures slot accuracy; routing by the parse result is not part of either change yet.
- **⚠️ To be decided**: whether to also build **true CAG** (choosing between "put the whole destination knowledge into the context" and RAG by token budget). The draft is in [`drafts/add-cag-mode/`](roadmap/drafts/add-cag-mode/). The two can be combined: LLM parsing decides "whether knowledge is needed", and the token budget decides "CAG or RAG". The draft was written against the old plan (it references the cancelled `knowledge-evaluation`) and must be rewritten when the change is formally created.
- **Category presets**: each of the 50 categories carries a preset tone and constraints that v0.1.0 puts into the prompt in place of the user's own words. `rebuild-rag` compared "preset only / user's words only / both" with a preference-adherence metric (its design decision 3) and adopted "both", the traveller's words first and the preset only where they say nothing (variant C, see `docs/experiments.md`). Neither `parse-requests` nor `clarify-requests` changes this. **Later experiment: drop the presets.** Variant B (the traveller's words only, no preset) had higher faithfulness with context (52.4% against 48.0%) and destination rate (93.2% against 89.0%), but lower preferences followed (92.4% against 97.7%). Dropping the presets would also take `cag_match` off the request path (mean step latency about 0.65 s in most evaluation runs, 1.42 s in the slowest, `20261108T130747Z`). Once requests are parsed, compare a template without the preset against the active one, with criteria set before the runs.
- **Side note**: asking the user back requires sessions, so design it together with item 5.

### 4. Tool calling (real agent capability)

- 2–3 genuinely useful tools: weather (Open-Meteo, free, no key needed), places and distances (OpenStreetMap / Nominatim, respecting the usage policy and rate limits), a budget calculator (computed by deterministic code, not letting the model do the addition).
- The main flow stays fixed; only in the "planning" step does the model decide which tools to call; limit the number of calls and the total time.
- After Nominatim is integrated, change "attractions really are in the destination" from a judge-model decision to a **code check** (`harden-workflow-guardrails` does not yet implement a runtime check); the place-name table in the input guardrails can also switch to Nominatim.
- **Plausible costs (gap found in the v0.1.0 baseline).** The budget constraint only caps the model's own estimates, and nothing grounds them (corpus v1 has no prices): an unrealistically low estimate passes, and `luxury` itineraries are not checked at all (e.g. 6,500–12,000 AUD per person per day, accepted as is). Add a dated reference price table — a plausible per-person daily range for each destination and budget level, excluding accommodation — used by the budget calculator and as an evaluation metric ("cost estimate within the plausible range"), and as a business rule once its numbers are trusted. Since `harden-workflow-guardrails` lets the user set their own daily ceiling (`max_daily_budget_aud`, for any level, including `luxury`), the table also checks the request: an amount below the plausible minimum for the destination (30 AUD a day in Sydney) should be asked back rather than planned, and a `luxury` request without an amount can get a loose default ceiling from it.
- **Feasible days (same baseline).** Nothing checks whether a day's plan fits in a day: one v0.1.0 itinerary has a helicopter transfer from Perth to Margaret River and back, a vineyard tour, a coastal drive and a spa on the same day. With the distance tool, compute travel time between consecutive stops and flag days whose travel plus a minimum time per activity exceeds the day; until then this can only be a judge question. Report it as a constraint ("days feasible") alongside trip length and budget.

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
- **`rebuild-rag` leaves no local reranking model to fit in**: Cross-Encoder reranking was measured at about 890 MB of process memory and not adopted (see `docs/experiments.md`). If a later change brings it back, choose between "smaller model / hosted reranking service / no reranking", justifying the trade-off with evaluation numbers.
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
