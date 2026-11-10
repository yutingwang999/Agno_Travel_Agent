# Design

## Context

See proposal.md for the motivation. The relevant current state:

- `POST /generate` takes the form (`TravelRequest`: `destination`, `trip_length`, `budget`, `travel_style`, optional `max_daily_budget_aud` and `notes`). Before the workflow starts it runs the prompt injection guard on every free-text field and the out-of-scope destination guard (place list, canonical names, Chinese names), rejecting with 422 and `{"reason", "detail"}`.
- The workflow (`intake → cag_match → retrieval_decision → rag_retrieve → generate → validate_output`) always retrieves since `rebuild-rag`; `cag_match` supplies the category preset that template v4 uses as a default.
- Every dataset entry has a `form`, an `utterance` (the same request as one sentence) and `gold_slots` (`destination`, `trip_length_days`, `budget`, `preferences`). In the 79 utterances the budget level is unstated in 17 `plan` entries; destination is missing only in `clarify` and `refuse` entries, trip length only in `refuse` entries; e074 states an amount ("about $50 a day each").
- `RunConfig.request_parser` exists and is always false; the slot extraction metric reports "N/A, no request parser". Observed behaviour has no `clarify` class, so the 7 `clarify` entries always count as wrong.

## Goals / Non-Goals

**Goals:**
- A free-text way in that ends in the same form and the same `/generate` call as the form way in, so generation is untouched and both ways can be compared on the same entries.
- Parser quality measured against `gold_slots` and each entry's `form`, separately from generation quality.

**Non-Goals:**
- Clarifying questions for contradictory or unfeasible requests, choices, and the fallback after one round (`clarify-requests`). This change only leaves required fields empty when the sentence does not give them.
- Changing category matching or the generation template (dropping the category presets is a separate experiment, recorded in the roadmap).
- Sessions or multi-turn conversation (roadmap item 5).
- Tools, MCP or external geography services (roadmap item 4).

## Decisions

### 1. Free text fills the form; generation stays as it is (two calls)

```
 "Describe your trip"                 "Fill in a form"
        |                                   |
        v                                   |
 POST /parse  -> request object             |
        |                                   |
        v                                   |
 form filled in, assumptions shown,         |
 empty required fields highlighted          |
 user reviews / edits ----------------------+
                                            v
                                POST /generate (unchanged)
```

The user sees and can correct what the parser understood before anything is generated, the form stays the single input of generation, and parsing can be evaluated on its own.

Alternative: `/generate` accepting either a sentence or a form, with parsing as a workflow step. One call instead of two, but a parsing mistake (the wrong destination) only shows after a full itinerary was generated, `/generate` gets two input shapes, and parse and generation quality are mixed in one run. Decided with the user (2026-11-10).

### 2. One structured-output call, no tools

The parser is one `gemini-3.1-flash-lite` call with a response schema (the same mechanism generate uses), returning: `is_travel_request`, `destination`, `trip_length`, `budget`, `max_daily_budget_aud`, `travel_style`, `notes`, `preferences`. Fields the sentence does not state are null. The prompt is a new versioned template key in `prompt_templates` (`request_parser`, seeded by `scripts/seed.py`), never hardcoded.

Alternatives: tool / function calling (useful when the model chooses actions; parsing has one fixed output shape, so structured output is simpler and easier to test); a stronger model (decided against for now: flash-lite first, compared only if slot accuracy is not good enough).

What the model does and what code does:

| Model | Code |
| --- | --- |
| Read the sentence into the fields; say whether it is a travel request | Injection check before the call; place-list lookup of the destination; the 1–14 day range; defaults and `assumptions`; the HTTP response |

`assumptions` come from code so that they are exactly the fields that were defaulted, not the model's own commentary.

### 3. Missing fields

| Field | When the sentence does not state it |
| --- | --- |
| `destination`, `trip_length` | Left empty and listed in `missing`; the form highlights them and generation needs them filled in |
| `budget` | `moderate`, with an assumption |
| `travel_style` | A general default (`"general sightseeing"`), with an assumption |
| `max_daily_budget_aud` | Empty (only a stated amount per person per day is taken; a total or a group amount stays in `notes`) |
| `notes` | Empty |

`notes` holds only the details the other fields cannot express ("Our kids are 6 and 9."), as the dataset's forms do, so that a correctly parsed sentence gives the same form as the form way in. A parsed `trip_length` outside 1–14 is left empty and listed in `missing`, so the form never carries a value `/generate` would reject.

### 4. Guards and refusals at parse time

```
 sentence
   |-- injection pattern? ----------------> 422 input_rejected   (no LLM call)
   v
 LLM parse
   |-- not a travel request? -------------> 422 not_a_travel_request
   |-- destination not in the place list? -> 422 destination_out_of_scope
   v
 200: request object (destination canonical, or empty)
```

The guards are the existing ones, reused, with the same fixed rejection bodies; `not_a_travel_request` is a new code with its own fixed message. An empty destination is not a rejection: it is a field for the user to fill in. `/generate` keeps all its guards, since the user can edit the form.

### 5. Tracing

`/parse` writes one trace row (`step_name` = `parse_request`, latency, template key and version, token usage, `error_type` on failure) under a new `parse_id` that it returns. Tracing never raises, as elsewhere. `/parse` returns one JSON body, not an SSE stream: it is a single step and the form needs the whole result at once.

### 6. Frontend

Two tabs above the existing form: "Describe your trip" (a text box and a "Fill in the form" button) and the form itself. After `/parse` the form tab opens with the fields filled in, each assumption shown next to its field, and empty required fields highlighted; a refusal shows the rejection message as the form does today. The user then generates as today.

### 7. Evaluating the free-text path

With `request_parser: true` a run sends each entry's `utterance` to `/parse`, then, when the parse returns a complete form, sends that form to `/generate` with the configuration's `template_version`. Nothing simulates the user's review: the harness takes the parse as it is.

Observed behaviour on this path: a parse rejection is `refuse` (as today); a parse that leaves `destination` or `trip_length` empty is `clarify`, because the user would be asked for those fields; otherwise the generate outcome (`plan`, `error`). A contradictory request that parses completely is still planned, and its `clarify` expectation still fails until `clarify-requests`.

Metrics added for a parser configuration, over `plan` entries:

- **Slot extraction accuracy** per slot against `gold_slots`: destination (canonical name), trip length and budget level exact, where a gold `budget` of null means "not stated" and is matched by the parser leaving the budget unstated (before the default is applied); preferences as recall, each gold preference counted as covered when a parsed preference or the parsed `travel_style` contains it, case-insensitively.
- **Field agreement** with the entry's `form`: `destination`, `trip_length`, `budget` (after defaults), `max_daily_budget_aud` exact; `notes` as presence agreement (both empty or both non-empty), since its wording is free.
- **Parser latency and cost**, from the `parse_request` trace row, reported separately and added to the per-request cost.

The judges keep receiving the dataset `form`'s `travel_style`, `notes` and `destination` on both paths: they measure whether the itinerary follows what the traveller asked, so a preference the parser drops shows up as a lower preferences-followed share, and the judge inputs stay the same as in the calibrated runs (no recalibration).

A parse-only mode (`--parse-only`, like `--retrieval-only`) sends only `/parse` and reports slot accuracy, field agreement, parse behaviour, latency and cost, for cheap iteration on the parser prompt.

### 8. Success criteria (proposed; to be confirmed with the user before the comparison runs)

Means of two runs on the same entries, free-text path against form path:

- Slot extraction accuracy: destination and trip length at least 95%, budget level at least 90%.
- Faithfulness with context and preferences followed within 2 points of the form path.
- `refuse` behaviour on the free-text path not lower than on the form path.
- `/parse` p50 latency at most 2 s.

### 9. Category matching unchanged

`cag_match` keeps matching on the form's fields, so both ways in get the same preset. Whether the presets are dropped (template B: higher faithfulness and destination rate in `rebuild-rag` task 5.4, lower preferences followed, and `cag_match` costs about 1.4 s) is a separate experiment.

## Risks / Trade-offs

- [The model invents a destination or trip length the sentence does not state] → the prompt says to leave unstated fields null; slot accuracy on entries without a gold value checks it; the user reviews the form before generating.
- [Default `travel_style` makes generation blander than the form way in] → measured by the path comparison (preferences followed); the default is shown as an assumption the user can edit.
- [`notes` drops a detail the traveller gave] → field agreement on `notes` and the preferences-followed comparison show it; the user can edit `notes`.
- [Injection hidden in the sentence reaches the parser] → the injection check runs on the sentence before the LLM call, and on the parsed fields again at `/generate`.
- [Mixed Chinese and English sentences] → the `mixed_language` and `chinese_destination` entries are in the dataset; the place list already maps Chinese names.
- [Two calls add latency for the free-text way in] → the parse is about one short flash-lite call; reported separately, with a criterion (decision 8).
- [`clarify` observed only for missing fields overstates readiness] → reported per tag; contradictory entries remain failures until `clarify-requests`.

## Migration Plan

1. Seed the `request_parser` template (no database migration; `prompt_templates` already holds versioned keys).
2. Deploy the endpoint, guards and frontend; `/generate` is unchanged, so existing clients are unaffected.
3. Rollback: remove the endpoint and the free-text tab; the template rows can stay.

## Open Questions

- Exact wording of the default `travel_style` and of the `not_a_travel_request` message: settled while writing the prompt and tests.
- Layout details of the two tabs.
