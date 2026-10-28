"""Retrieval metrics: Recall@k and MRR@k against section-level relevance labels.

Every entry with ``relevant_sections`` is measured, whether or not the workflow
would route it to retrieval: intake and intent matching run first, the query is
built by the workflow's own code, and the retrieval component is called directly.

Public API::

    from evaluation.retrieval import evaluate_entry, summarize, workflow_query_text

    result = evaluate_entry(entry, query_fn=workflow_query_text, retrieve_fn=..., k=5)
    summary = summarize([result, ...])
"""

from dataclasses import dataclass
from typing import Callable

from agno.workflow.types import StepInput, StepOutput

from evaluation.dataset import DatasetEntry

DEFAULT_K = 5
HANDWRITTEN_SOURCE = "handwritten"

Section = tuple[str, str]


@dataclass(frozen=True)
class RetrievalResult:
    entry_id: str
    query_text: str
    retrieved: list[Section]
    recall: float
    reciprocal_rank: float


def chunk_section(chunk) -> Section:
    """Return the ``(source, section)`` a retrieved chunk is labelled by.

    Chunks without a ``section`` field (the v0.1.0 handwritten documents) are
    identified as ``("handwritten", <title>)``.
    """
    metadata = chunk.metadata or {}
    if metadata.get("section"):
        return (str(metadata.get("source", "")), str(metadata["section"]))
    return (HANDWRITTEN_SOURCE, chunk.title)


def recall_at_k(ranked: list[Section], relevant: set[Section], k: int) -> float:
    """Share of relevant sections found in the top-k results (several chunks of one section count once)."""
    if not relevant:
        raise ValueError("recall is undefined without relevant sections")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[Section], relevant: set[Section], k: int) -> float:
    """1 / rank of the first relevant result within the top k, or 0 when there is none."""
    for rank, section in enumerate(ranked[:k], start=1):
        if section in relevant:
            return 1.0 / rank
    return 0.0


def workflow_query_text(form: dict, session_id: str = "eval-retrieval") -> str:
    """Run intake and intent matching for *form* and build the query as ``rag_retrieve`` does.

    Needs the database and Gemini API key the workflow itself uses (cag_match
    embeds the request); intake and cag_match write their usual trace rows.
    """
    from app.main import build_additional_data
    from app.workflow.intake_model import TravelRequest
    from app.workflow.steps.cag_match import cag_match_executor
    from app.workflow.steps.intake import intake_executor
    from app.workflow.steps.rag_retrieve import _build_query_text

    additional_data = build_additional_data(session_id, TravelRequest.model_validate(form))
    step_input = StepInput(additional_data=additional_data)
    previous: dict[str, StepOutput] = {
        "intake": intake_executor(step_input),
        "cag_match": cag_match_executor(step_input),
    }
    for name, output in previous.items():
        output.step_name = name
    return _build_query_text(
        StepInput(additional_data=additional_data, previous_step_outputs=previous)
    )


def evaluate_entry(
    entry: DatasetEntry,
    query_fn: Callable[[dict], str],
    retrieve_fn: Callable[[str], list],
    k: int = DEFAULT_K,
) -> RetrievalResult:
    """Measure one entry: build its query, retrieve, and score against its labels."""
    relevant = {(s.source, s.section) for s in entry.relevant_sections}
    query_text = query_fn(entry.form.model_dump(exclude_none=True))
    ranked = [chunk_section(chunk) for chunk in retrieve_fn(query_text)]
    return RetrievalResult(
        entry_id=entry.id,
        query_text=query_text,
        retrieved=ranked,
        recall=recall_at_k(ranked, relevant, k),
        reciprocal_rank=reciprocal_rank(ranked, relevant, k),
    )


def summarize(results: list[RetrievalResult], k: int = DEFAULT_K) -> dict:
    """Mean Recall@k and MRR@k over the measured entries."""
    if not results:
        return {"k": k, "entries": 0, "recall_at_k": None, "mrr_at_k": None}
    return {
        "k": k,
        "entries": len(results),
        "recall_at_k": sum(r.recall for r in results) / len(results),
        "mrr_at_k": sum(r.reciprocal_rank for r in results) / len(results),
    }


def measurable_entries(entries: list[DatasetEntry]) -> list[DatasetEntry]:
    """Entries that have relevance labels; only these are scored."""
    return [entry for entry in entries if entry.relevant_sections]
