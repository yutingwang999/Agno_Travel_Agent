## REMOVED Requirements

### Requirement: Conditional execution
**Reason**: Retrieval was gated on intent confidence; it is now gated on the knowledge mode.
**Migration**: See "Retrieval mode execution" below and `knowledge-context` — "Knowledge mode decision".

## ADDED Requirements

### Requirement: Retrieval mode execution
The `rag_retrieve` step SHALL run only when the knowledge mode chosen by `retrieval_decision` is `"rag"`; when it is `"cag"`, the `cag_context` step runs instead and no `rag_retrieve` event or trace row is produced.

#### Scenario: CAG mode chosen
- **WHEN** the knowledge mode is `"cag"`
- **THEN** no `rag_retrieve` event is emitted

#### Scenario: RAG mode chosen
- **WHEN** the knowledge mode is `"rag"`
- **THEN** `rag_retrieve` runs and `cag_context` does not
