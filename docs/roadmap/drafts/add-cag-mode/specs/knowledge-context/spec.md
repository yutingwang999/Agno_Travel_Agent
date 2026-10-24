## Purpose
Defines how the workflow decides between Cache-Augmented Generation (all destination knowledge placed in the generation context) and Retrieval-Augmented Generation (top-k retrieval), based on how much knowledge exists for the destination, and how the CAG knowledge context is assembled and optionally cached.

## ADDED Requirements

### Requirement: Knowledge mode decision
The `retrieval_decision` step SHALL select the knowledge chunks eligible for the request (destination equal to the request destination or `"australia"`, or only `"australia"` when the destination has no chunks), count their tokens, and choose `"cag"` when that count is at or below `KNOWLEDGE_TOKEN_BUDGET` and `"rag"` otherwise. The intent classification confidence SHALL NOT affect this decision.

#### Scenario: Small destination corpus
- **WHEN** the eligible chunks for `"sydney"` total 12,000 tokens and the budget is 32,000
- **THEN** the knowledge mode is `"cag"`

#### Scenario: Large destination corpus
- **WHEN** the eligible chunks total 50,000 tokens and the budget is 32,000
- **THEN** the knowledge mode is `"rag"`

#### Scenario: Confidence is ignored
- **WHEN** two requests for the same destination have intent confidence 0.95 and 0.20
- **THEN** both get the same knowledge mode

### Requirement: Configurable token budget
`KNOWLEDGE_TOKEN_BUDGET` SHALL be read from the environment, falling back to a default defined in `app.workflow.config`; the default's value and the experiment that justifies it SHALL be recorded in `docs/experiments.md`.

#### Scenario: Override by environment
- **WHEN** `KNOWLEDGE_TOKEN_BUDGET` is set to `8000`
- **THEN** the knowledge mode decision uses 8,000 as the budget

### Requirement: Knowledge mode event
The `retrieval_decision` event `data` SHALL contain `knowledge_mode` (`"cag"` or `"rag"`), `knowledge_tokens`, `token_budget`, and `destination_matched`, and SHALL be emitted for every request.

#### Scenario: Decision visible in stream
- **WHEN** the CAG mode is chosen
- **THEN** the stream contains a `retrieval_decision` event with `knowledge_mode` = `"cag"` and the token count used

### Requirement: CAG context assembly
When the knowledge mode is `"cag"`, a `cag_context` step SHALL emit every eligible chunk, ordered with destination chunks before `"australia"` chunks and then by `source` and `section`, in the same chunk shape that `rag_retrieve` uses. Its event `data` SHALL contain `knowledge_context` (the chunk list) and `chunks_included`.

#### Scenario: All eligible chunks included
- **WHEN** the CAG mode is chosen for `"sydney"` with 80 eligible chunks
- **THEN** the `cag_context` event has `chunks_included` = 80

#### Scenario: Stable order
- **WHEN** the same request is made twice with an unchanged corpus
- **THEN** both `cag_context` events list the chunks in the same order

### Requirement: Context cache fallback
The generate step MAY reuse a provider-side cached copy of the CAG knowledge context; if creating or using the cache fails, or the context is below the provider's minimum cacheable size, it SHALL place the context inline in the prompt and continue. The generate event and trace SHALL record `context_cached` as true or false.

#### Scenario: Cache unavailable
- **WHEN** creating the context cache raises an error
- **THEN** generation proceeds with the context inline and `context_cached` is `false`
