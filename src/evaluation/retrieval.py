"""Retrieval metrics: Recall@k and MRR@k against section-level relevance labels.

Every entry with ``relevant_sections`` is measured, whether or not the workflow
would route it to retrieval: intake and intent matching run first, the query is
built by the workflow's own code, and the retrieval component is called directly.

Public API::

    from evaluation.retrieval import evaluate_entry, summarize, workflow_query_text

    result = evaluate_entry(entry, query_fn=workflow_query_text, retrieve_fn=..., k=5)
    summary = summarize([result, ...])
"""

import os
from dataclasses import dataclass
from typing import Callable, Literal

from agno.workflow.types import StepInput, StepOutput

from evaluation.dataset import DatasetEntry

DEFAULT_K = 5
HANDWRITTEN_SOURCE = "handwritten"

Section = tuple[str, str]

# How the matched category enters a measured query. "current" is what the workflow does;
# the others exist only to compare query constructions (rebuild-rag task 4.7).
QueryCategory = Literal["current", "no_budget", "no_category"]


@dataclass(frozen=True)
class RetrievalResult:
    entry_id: str
    query_text: str
    retrieved: list[Section]
    recall: float
    reciprocal_rank: float


def chunk_section(chunk) -> Section:
    """Return the ``(source, section)`` a retrieved chunk is labelled by.

    A chunk from a corpus page is identified by its page and section, so the same
    section of two pages stays apart. Handwritten documents, which have no ``section``
    field in corpus v1, are identified as ``("handwritten", <title>)``.
    """
    metadata = chunk.metadata or {}
    if metadata.get("section") and metadata.get("source") != HANDWRITTEN_SOURCE:
        return (chunk.title, str(metadata["section"]))
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


def workflow_destination(form: dict) -> str:
    """The destination the workflow retrieves for: canonical, as POST /generate makes it."""
    from app.workflow.input_guard import guard_request
    from app.workflow.intake_model import TravelRequest

    return guard_request(TravelRequest.model_validate(form)).destination


def _cag_match_without_budget(additional_data: dict, session_id: str) -> StepOutput:
    """A cag_match event whose category was matched on an intent text without the budget phrase."""
    from app.workflow.cag_matcher import match_category
    from app.workflow.sse import build_sse_event, sse_event_to_json

    result = match_category(
        intent_text=f"{additional_data['travel_style']} trip to {additional_data['destination']}",
        db_url=os.environ["DATABASE_URL"],
        api_key=os.environ["GEMINI_API_KEY"],
        embedding_model=os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"),
    )
    event = build_sse_event(
        session_id=session_id,
        step="cag_match",
        status="completed",
        data={"matched_category": result.category_key},
    )
    return StepOutput(content=sse_event_to_json(event))


def workflow_query_text(
    form: dict,
    session_id: str = "eval-retrieval",
    *,
    include_notes: bool = True,
    category: QueryCategory = "current",
) -> str:
    """Run intake and intent matching for *form* and build the query as ``rag_retrieve`` does.

    Needs the database and Gemini API key the workflow itself uses (cag_match
    embeds the request); intake and cag_match write their usual trace rows.

    With the defaults this is the workflow's query. *include_notes* and *category*
    measure other query constructions, which the workflow never sends.
    """
    from app.main import build_additional_data
    from app.workflow.input_guard import guard_request
    from app.workflow.intake_model import TravelRequest
    from app.workflow.steps.cag_match import cag_match_executor
    from app.workflow.steps.intake import intake_executor
    from app.workflow.steps.rag_retrieve import _build_query_text

    # guard_request as POST /generate does: it replaces the destination by its canonical name.
    request = guard_request(TravelRequest.model_validate(form))
    if not include_notes:
        request = request.model_copy(update={"notes": None})
    additional_data = build_additional_data(session_id, request)
    step_input = StepInput(additional_data=additional_data)
    previous: dict[str, StepOutput] = {"intake": intake_executor(step_input)}
    if category == "current":
        previous["cag_match"] = cag_match_executor(step_input)
    elif category == "no_budget":
        previous["cag_match"] = _cag_match_without_budget(additional_data, session_id)
    elif category != "no_category":
        raise ValueError(f"unknown query category {category!r}")
    for name, output in previous.items():
        output.step_name = name
    return _build_query_text(
        StepInput(additional_data=additional_data, previous_step_outputs=previous)
    )


def evaluate_entry(
    entry: DatasetEntry,
    query_fn: Callable[[dict], str],
    retrieve_fn: Callable[[str, dict], list],
    k: int = DEFAULT_K,
) -> RetrievalResult:
    """Measure one entry: build its query, retrieve, and score against its labels."""
    relevant = {(s.source, s.section) for s in entry.relevant_sections}
    form = entry.form.model_dump(exclude_none=True)
    query_text = query_fn(form)
    ranked = [chunk_section(chunk) for chunk in retrieve_fn(query_text, form)]
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
