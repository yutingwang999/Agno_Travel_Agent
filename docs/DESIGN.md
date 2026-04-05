# DESIGN.md

## 1. Domain Choice and Rationale

### Chosen Domain

Travel Itinerary Planner in Australia

### Why this domain

I chose a travel itinerary planning domain because it provides a natural balance between structured inputs and free-text intent, while also making it easy to demonstrate all required AI workflow patterns.

This domain allows:

- Structured inputs (destination, trip_length, budget, travel_style)
- Free-text intent understanding
- Semantic classification via CAG
- Context enrichment via RAG
- Strongly structured outputs suitable for validation

It also keeps the dataset relatively small and interpretable, which is important for a prototype constrained to 8–10 hours.

### Design intent

The goal of this system is not to maximise feature complexity, but to clearly demonstrate:

- separation of concerns between CAG and RAG
- database-driven prompt construction
- observable and testable AI behaviour
- safe handling of model outputs

---

## 2. Evaluation Mapping

To ensure alignment with evaluation criteria, key design decisions are explicitly mapped below:

| Evaluation focus      | Design decision                              | Evidence in system                 |
| --------------------- | -------------------------------------------- | ---------------------------------- |
| AI-first architecture | Agno workflow with Step + Condition          | Step-based workflow with branching |
| CAG vs RAG clarity    | CAG = intent classification, RAG = knowledge | retrieval_decision step            |
| Prompt governance     | DB-stored, versioned templates               | prompt_templates + trace logging   |
| Reliability           | Pydantic validation + retry                  | validate_output step               |
| Observability         | Structured trace + SSE                       | trace_events + SSE schema          |
| Testing               | layered + golden tests                       | defined acceptance criteria        |

This mapping ensures that the implementation is not only functional but also aligned with how the system will be evaluated.

---

## 3. System Architecture

### High-level architecture

Browser UI  
→ POST /generate  
→ receives SSE stream

FastAPI Service  
→ request validation  
→ session_id creation  
→ executes Agno workflow  
→ streams structured events

Agno Workflow

1. intake
2. cag_match
3. retrieval_decision (Condition)
4. rag_retrieve (conditional)
5. generate
6. validate_output

PostgreSQL

- reference tables
- prompt templates
- trace events
- document metadata

pgvector

- vector search for RAG

Support Modules

- template resolver
- CAG matcher
- retrieval service
- output validator
- trace logger

### Request flow

1. User submits a travel planning request
2. Intake validates and normalises input
3. CAG classifies user intent into itinerary type
4. Conditional logic determines if retrieval is needed
5. RAG retrieves contextual knowledge if required
6. Generation constructs prompt from DB templates and calls LLM
7. Validation enforces schema and guardrails
8. Result is streamed step-by-step via SSE

---

## 4. Design Decisions to Limit AI-First Risks

This system intentionally avoids over-reliance on generated code and focuses on controlled orchestration.

Key decisions:

- Use Agno primitives instead of building a custom workflow engine
- Use pgvector integration instead of custom retrieval logic
- Store prompts in database to allow inspection and versioning
- Enforce schema validation on all outputs
- Log all steps for traceability

Why this matters:

- Prevents hidden model failures
- Improves debuggability
- Makes behaviour reproducible
- Reduces “black box” risks in AI systems

---

## 5. Data Model and Persistence Plan

### Core tables

#### itinerary_categories

- id
- category_key
- description
- tone
- constraints
- embedding_vector

Purpose:  
Supports semantic matching and prompt variable resolution.

---

#### prompt_templates

- id
- template_key
- version
- template_text
- is_active
- created_at

Purpose:  
Supports prompt versioning and controlled experimentation.

---

#### source_documents

- id
- destination
- title
- chunk_text
- embedding_vector
- metadata_json

Purpose:  
Stores knowledge base for RAG retrieval.

---

#### trace_events

- id
- session_id
- step_name
- status
- latency_ms
- prompt_template_key
- prompt_template_version
- error_type
- degraded_mode
- created_at

Purpose:  
Enables observability and debugging.

---

### Design rationale

- Separation of reference data and retrieval data ensures clarity
- Prompt templates are versioned to support reproducibility
- Trace schema is structured for debugging and evaluation

---

## 6. Workflow Step Breakdown

### Step 1: intake

Validates input and normalises fields.

---

### Step 2: cag_match

Maps free-text intent to category using embeddings.

Output:

- matched_category
- confidence_score

---

### Step 3: retrieval_decision

Determines whether RAG is needed.

Threshold:

- default = 0.78

Rationale:  
This threshold balances retrieval cost with relevance quality.

---

### Step 4: rag_retrieve

Retrieves top-k relevant documents.

Defaults:

- top_k = 5

---

### Step 5: generate

Constructs prompt from DB template and calls LLM.

---

### Step 6: validate_output

Validates using Pydantic schema and applies guardrails.

If validation fails:

- retry once with corrective prompt
- otherwise return structured error

---

## 7. Prompt Template Strategy

### Template types

- high_confidence_minimal_context
- low_confidence_with_retrieval

### Variables

- destination
- trip_length
- budget
- matched_category
- tone
- constraints
- retrieved_context

### Strategy

- High confidence → minimal prompt
- Low confidence → retrieval-augmented prompt

### Versioning

- One active version per template
- Optional override via request parameter
- Logged in trace for reproducibility

---

## 8. CAG vs RAG Boundary

### CAG

Used for:

- intent classification
- fast, deterministic mapping

### RAG

Used for:

- factual enrichment
- dynamic context injection

### Design decision

CAG answers: what to generate  
RAG answers: what information to include

---

## 9. SSE Contract and Observability

### SSE event structure

{
"session_id": "...",
"step": "cag_match",
"status": "completed",
"timestamp": "...",
"data": {},
"error": null
}

### Why structured SSE

- Enables UI progress tracking
- Improves debugging
- Makes workflow observable

---

## 10. Error Handling Strategy

- Intake: return 422
- CAG: fallback to default category
- RAG: degrade gracefully
- Generation: structured error
- Validation: retry once

All failures are logged with:

- session_id
- step_name
- error_type

---

## 11. Testing Strategy

### Unit

- template resolver
- threshold logic
- validation helpers

### Integration

- DB migrations
- prompt lookup
- trace logging

### End-to-end

- full workflow via POST → SSE

### Golden tests

1. family trip
2. budget trip
3. low-confidence request

Focus:

- structure
- semantics
- branch correctness

---

## 12. Open Questions and Assumptions

### Questions

- Expected latency per request?
- Should responses include source attribution?
- Any constraints on token usage?

### Assumptions

- single LLM provider is sufficient
- simple UI is acceptable
- 10–20 documents are enough for RAG

---

## 13. Reviewer Notes

This design prioritises:

- clarity over complexity
- reproducibility over optimisation
- observability over abstraction

The system is intentionally simple but complete, ensuring that each required capability is implemented, testable, and explainable.
