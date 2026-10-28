"""build-evaluation-harness: retrieval metrics (Recall@k, MRR@k) and query construction.

No database or API key: intent matching and retrieval are mocked.
"""

import pytest

from app.workflow.retrieval_service import RetrievedChunk
from evaluation.dataset import DatasetEntry
from evaluation.retrieval import (
    chunk_section,
    evaluate_entry,
    measurable_entries,
    recall_at_k,
    reciprocal_rank,
    summarize,
    workflow_query_text,
)

A, B, C, D = (("handwritten", name) for name in ("A", "B", "C", "D"))


def _chunk(title: str, **metadata) -> RetrievedChunk:
    return RetrievedChunk(destination="Australia", title=title, chunk_text="...", metadata=metadata)


def _entry(sections: list[str]) -> DatasetEntry:
    return DatasetEntry.model_validate({
        "id": "t001",
        "tags": [],
        "form": {"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "family"},
        "utterance": "3 days in Sydney with the family",
        "gold_slots": {"destination": "sydney", "trip_length_days": 3, "budget": None, "preferences": ["family"]},
        "expected_behavior": "plan",
        "relevant_sections": [{"source": "handwritten", "section": s} for s in sections],
    })


# ---------------------------------------------------------------------------
# Metrics on hand-built rankings
# ---------------------------------------------------------------------------


def test_recall_counts_relevant_sections_in_top_k():
    assert recall_at_k([A, C, B], {A, B}, k=3) == 1.0
    assert recall_at_k([A, C, B], {A, B}, k=2) == 0.5
    assert recall_at_k([C, D], {A, B}, k=5) == 0.0


def test_recall_counts_a_section_once_even_with_several_chunks():
    assert recall_at_k([A, A, A], {A, B}, k=3) == 0.5


def test_recall_without_labels_is_an_error():
    with pytest.raises(ValueError):
        recall_at_k([A], set(), k=5)


def test_reciprocal_rank_uses_first_relevant_result():
    assert reciprocal_rank([A, B], {A}, k=5) == 1.0
    assert reciprocal_rank([C, D, B], {A, B}, k=5) == pytest.approx(1 / 3)
    assert reciprocal_rank([C, D, B], {B}, k=2) == 0.0
    assert reciprocal_rank([], {A}, k=5) == 0.0


def test_summarize_averages_over_entries():
    from evaluation.retrieval import RetrievalResult

    results = [
        RetrievalResult("e1", "q", [A], recall=1.0, reciprocal_rank=1.0),
        RetrievalResult("e2", "q", [C, B], recall=0.5, reciprocal_rank=0.5),
    ]
    assert summarize(results) == {"k": 5, "entries": 2, "recall_at_k": 0.75, "mrr_at_k": 0.75}
    assert summarize([])["recall_at_k"] is None


# ---------------------------------------------------------------------------
# Section identity of retrieved chunks
# ---------------------------------------------------------------------------


def test_v1_chunk_without_section_is_handwritten_title():
    """Spec scenario: a v0.1.0 document is matched as ("handwritten", <title>)."""
    chunk = _chunk("Family Adventure Travel in Australia", source="some-source", category="family")
    assert chunk_section(chunk) == ("handwritten", "Family Adventure Travel in Australia")


def test_chunk_with_source_and_section_uses_them():
    chunk = _chunk("Sydney", source="wikivoyage:Sydney", section="See")
    assert chunk_section(chunk) == ("wikivoyage:Sydney", "See")


# ---------------------------------------------------------------------------
# evaluate_entry
# ---------------------------------------------------------------------------


def test_evaluate_entry_scores_retrieved_chunks():
    entry = _entry(["Guide to Sydney", "Family Adventure Travel in Australia"])
    chunks = [_chunk("Guide to Melbourne"), _chunk("Guide to Sydney"), _chunk("Guide to Brisbane")]
    seen = {}

    def retrieve(query_text):
        seen["query"] = query_text
        return chunks

    result = evaluate_entry(entry, query_fn=lambda form: f"q:{form['destination']}", retrieve_fn=retrieve)

    assert seen["query"] == "q:Sydney"
    assert result.recall == 0.5
    assert result.reciprocal_rank == 0.5
    assert result.retrieved[1] == ("handwritten", "Guide to Sydney")


def test_evaluate_entry_passes_notes_to_query_fn():
    entry = _entry(["Guide to Sydney"])
    entry.form.notes = "kids are 6 and 9"
    forms = []
    evaluate_entry(entry, query_fn=lambda form: forms.append(form) or "q", retrieve_fn=lambda q: [])
    assert forms[0]["notes"] == "kids are 6 and 9"


def test_measurable_entries_skips_entries_without_labels():
    labelled, unlabelled = _entry(["Guide to Sydney"]), _entry([])
    assert measurable_entries([labelled, unlabelled]) == [labelled]


# ---------------------------------------------------------------------------
# Query text matches the workflow's
# ---------------------------------------------------------------------------


def _match(confidence: float):
    from app.workflow.cag_matcher import MatchResult

    return MatchResult(
        category_key="family",
        confidence_score=confidence,
        tone="friendly",
        constraints="kid friendly",
        is_fallback=False,
    )


@pytest.fixture
def mocked_workflow(monkeypatch):
    """Run the real Agno workflow with intent matching, retrieval and the LLM mocked."""
    from app.workflow.llm_usage import LLMResult

    valid = (
        '{"destination": "Sydney", "trip_length_days": 3, "budget_level": "moderate",'
        ' "travel_style": "family", "daily_itinerary": ['
        + ", ".join(
            f'{{"day": {d}, "morning": "m", "afternoon": "a", "evening": "e", "estimated_cost_aud": 50.0}}'
            for d in (1, 2, 3)
        )
        + '], "total_estimated_cost_aud": 150.0, "key_tips": ["t"]}'
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.workflow.steps.cag_match.match_category", lambda **kwargs: _match(0.5))
    queries: list[str] = []
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.retrieve_documents",
        lambda query_text, **kwargs: queries.append(query_text) or [],
    )
    monkeypatch.setattr(
        "app.workflow.steps.generate.resolve_template",
        lambda template_key, db_url, version=None: ("Plan {destination}.", 1),
    )
    monkeypatch.setattr("app.workflow.steps.generate._call_llm", lambda prompt, api_key, model: LLMResult(valid))
    return queries


def test_query_text_matches_the_workflow(mocked_workflow):
    """The harness's query is exactly what rag_retrieve sends inside a real workflow run."""
    from app.main import _run_workflow
    from app.workflow.intake_model import TravelRequest

    form = {"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "family"}
    _run_workflow("sid-workflow", TravelRequest.model_validate(form))

    assert len(mocked_workflow) == 1
    assert workflow_query_text(form) == mocked_workflow[0]


def test_query_text_is_built_even_for_high_confidence(monkeypatch):
    """Spec scenario: an entry that would skip retrieval still gets the workflow's query."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.workflow.steps.cag_match.match_category", lambda **kwargs: _match(0.95))

    form = {"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "family"}
    assert workflow_query_text(form) == "family travel in sydney family itinerary"
