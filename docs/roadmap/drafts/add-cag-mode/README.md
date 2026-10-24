# Draft: add-cag-mode

This is a **draft**, not an active OpenSpec change. It was moved out of `openspec/changes/` because it is scheduled after the near-term changes and depends on an open decision (roadmap item 3: LLM request parsing vs. token-budget CAG/RAG routing).

It was written against an earlier plan and is now out of date:

- It references the `knowledge-evaluation` capability, which was replaced by `evaluation-harness` (introduced by `build-evaluation-harness`).
- It does not account for citations (`rebuild-rag`), the guardrails in `harden-workflow-guardrails`, or multi-turn sessions (roadmap item 5).

When this work is picked up, create a fresh change with `openspec new change` and rewrite the deltas against the main specs at that time, reusing the reasoning in `proposal.md` and `design.md` here.
