# CLAUDE.md

> **v0.1.0 document.** Behaviour is now changed deliberately through OpenSpec (`openspec/changes/`, `openspec/specs/`), which takes precedence over this file and `DESIGN.md` where they conflict. See the root `CLAUDE.md` → "Sources of truth".

## Purpose

This file defines how AI tools (e.g. Claude, ChatGPT, Copilot) must operate in this repository.

The goal is to ensure:

- correctness of implementation
- consistency with system design
- safe and controlled code changes
- maintainability and explainability

This project follows an **AI-assisted development approach**, not AI-generated replacement.

---

## Source of Truth

- `DESIGN.md` is the **single source of truth** for system design
- If code and design conflict → **DESIGN.md is correct**
- Do NOT introduce behavior that contradicts DESIGN.md

If DESIGN.md is:

- unclear
- incomplete
- ambiguous

You MUST:

- pause
- ask for clarification
- avoid guessing critical logic

---

## Project Overview (Context for AI)

This system is built using:

- FastAPI (API layer)
- Agno (workflow orchestration)
- PostgreSQL + pgvector (data + vector storage)
- SSE (streaming responses)
- Pydantic (output validation)

Core capabilities:

- CAG (semantic matching)
- RAG (retrieval-augmented generation)
- conditional workflow branching
- database-driven prompt templates
- structured tracing and observability

---

## Mandatory Architecture Constraints

AI-generated code MUST follow these rules:

### Workflow Structure

The system must follow EXACTLY:

1. intake
2. cag_match
3. retrieval_decision (Condition)
4. rag_retrieve (conditional)
5. generate
6. validate_output

Do NOT:

- skip steps
- merge steps
- reorder logic

---

### CAG vs RAG Separation

- CAG = intent classification using reference data
- RAG = knowledge retrieval using pgvector

These must remain strictly separated.

---

### Prompt Handling

- Prompts MUST NOT be hardcoded
- Prompts MUST be stored in database
- Prompts MUST support versioning
- Prompt version must be traceable

---

### Validation

- All outputs MUST be validated using Pydantic
- Invalid outputs MUST:
  - trigger retry OR
  - return structured error

---

### Observability

- Every step MUST:
  - emit SSE event
  - write trace data

- All logs MUST include:
  - session_id
  - step_name

---

### Preferred Implementations

Prefer:

- Agno primitives (`Step`, `Condition`)
- pgvector integration
- standard libraries (SQLAlchemy, Pydantic)

Avoid:

- custom workflow engines
- custom vector search logic
- duplicating framework features

---

## AI Usage Principles

### 1. AI is a tool, not the decision-maker

- AI can generate code, but decisions must be human-controlled
- Never accept generated code without understanding it
- All code must be explainable

---

### 2. Incremental generation only

DO NOT:

- generate entire systems at once

DO:

- generate small components
- validate each step before continuing

---

### 3. Always validate AI output

Before accepting code:

- check correctness
- ensure alignment with DESIGN.md
- verify consistency with existing code

If uncertain:

- ask AI to explain
- request alternatives

---

## General Workflow for AI

### 1. Understand before acting

Before making changes:

- read DESIGN.md
- inspect relevant code
- identify gaps vs design

---

### 2. Plan first (required for non-trivial tasks)

Before coding:

- produce a plan including:
  - task breakdown
  - files to modify
  - risks
  - open questions

For complex changes:

- wait for confirmation before proceeding

---

### 3. Incremental implementation

- implement ONE task at a time
- avoid large multi-area changes

---

### 4. Validate after each step

- run tests (if available)
- check regressions
- verify DESIGN.md alignment

---

## Coding Guidelines

### Architecture

- follow DESIGN.md structure
- respect module boundaries
- do NOT introduce new architecture without approval

---

### Code Style

- prefer readability
- keep functions small and focused
- follow existing conventions

---

### Naming

- use descriptive names
- avoid vague names

---

## Database Rules

- Use PostgreSQL with pgvector
- Store:
  - reference data
  - prompt templates
  - trace logs
  - document chunks

- Use migrations (Alembic)
- Include seed data

---

## SSE Requirements

AI-generated API code MUST:

- return Server-Sent Events
- emit structured step events
- include:
  - session_id
  - step name
  - status

---

## Testing Requirements

AI should assist with tests, but:

Must include:

- unit tests
- integration tests
- end-to-end tests
- golden tests (AI behaviour)

Golden tests should:

- validate structure
- validate semantics
- NOT rely on exact string matching

---

## Refactoring Rules

- refactor only when necessary
- avoid unrelated changes
- preserve behavior unless DESIGN.md requires change

---

## Safety Rules

DO NOT:

- modify database schema without confirmation
- change public APIs without approval
- introduce dependencies without justification
- delete large code sections without explanation

---

## When Unsure

If:

- requirements are ambiguous
- multiple approaches exist
- system impact is large

You MUST:

- pause
- propose options
- ask for clarification

---

## Output Expectations

For every task, provide:

1. summary of changes
2. files modified
3. assumptions made
4. deviations from DESIGN.md
5. suggested next steps

---

## Preferred Working Style

- be precise, not verbose
- make minimal correct changes
- prioritize correctness over speed
- avoid speculative implementations

---

## Optional Commands

When applicable:

- run tests
- run linters
- run build

If a command fails:

- attempt fix
- otherwise report clearly

---

## Final Rule

Do not rush to code.

Think → Plan → Confirm → Implement → Verify
