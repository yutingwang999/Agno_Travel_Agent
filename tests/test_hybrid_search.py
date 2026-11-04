"""rebuild-rag step c: BM25 + vector candidates fused with RRF. All text is made up; no database."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agno.knowledge.document.base import Document

from app.workflow import hybrid_search as hybrid
from app.workflow import retrieval_service


def _document(chunk_id: str, content: str) -> Document:
    return Document(name="Testville", content=content, meta_data={"chunk_id": chunk_id, "destination": "testville"})


DOCUMENTS = [
    _document("zoo", "A large zoo with giraffes and a children's farm."),
    _document("market", "A weekend market selling crafts and local cheese."),
    _document("gallery", "The national gallery holds a famous painting collection."),
    _document("lane", "Hosier Lane is covered in graffiti."),
]


@pytest.fixture(autouse=True)
def documents(monkeypatch):
    hybrid._keyword_index.cache_clear()
    monkeypatch.setattr(hybrid, "_load_documents", lambda db_url, table, destination: DOCUMENTS)
    yield
    hybrid._keyword_index.cache_clear()


def _knowledge(vector_results: list[Document]) -> MagicMock:
    knowledge = MagicMock()
    knowledge.vector_db = SimpleNamespace(db_url="postgresql://fake", table_name="t")
    knowledge.search.return_value = vector_results
    return knowledge


def test_rrf_scores_by_rank_in_every_ranking():
    assert hybrid.reciprocal_rank_fusion([["a", "b"], ["b", "c"]]) == ["b", "a", "c"]


def test_rrf_gives_the_published_score_order_with_the_usual_constant():
    # b: 1/62 + 1/61; a: 1/61 alone; c: 1/62 alone.
    ranked = hybrid.reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)

    assert ranked.index("b") < ranked.index("a") < ranked.index("c")


def test_rrf_keeps_first_seen_order_on_a_tie():
    assert hybrid.reciprocal_rank_fusion([["a"], ["b"]]) == ["a", "b"]


def test_keyword_search_finds_a_rare_term():
    results = hybrid.keyword_search("Hosier Lane", "postgresql://fake", "t", None)

    assert results[0].meta_data["chunk_id"] == "lane"


def test_keyword_search_leaves_out_documents_without_a_query_term():
    results = hybrid.keyword_search("graffiti", "postgresql://fake", "t", None)

    assert [d.meta_data["chunk_id"] for d in results] == ["lane"]


def test_keyword_search_ignores_case():
    assert hybrid.keyword_search("GRAFFITI", "postgresql://fake", "t", None)


def test_keyword_only_chunk_can_be_selected():
    """Task 4.3: a chunk only keyword search finds still becomes a candidate."""
    vector_only = [_document("zoo", "A large zoo with giraffes and a children's farm.")]

    results = hybrid.hybrid_search(_knowledge(vector_only), "Hosier Lane", 5, None, None)

    assert "lane" in [d.meta_data["chunk_id"] for d in results]


def test_chunk_found_by_both_searches_ranks_first():
    both = _document("lane", "Hosier Lane is covered in graffiti.")
    vector = [_document("zoo", "A large zoo with giraffes and a children's farm."), both]

    results = hybrid.hybrid_search(_knowledge(vector), "Hosier Lane graffiti", 5, None, None)

    assert results[0].meta_data["chunk_id"] == "lane"


def test_result_is_cut_to_top_k_and_has_no_duplicates():
    vector = [_document(str(i), f"Made up text number {i}.") for i in range(10)]

    results = hybrid.hybrid_search(_knowledge(vector), "made up text", 3, None, None)

    ids = [d.meta_data["chunk_id"] for d in results]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_vector_search_is_asked_for_candidates_with_the_filter():
    knowledge = _knowledge([])
    filters = ["a filter"]

    hybrid.hybrid_search(knowledge, "query", 5, filters, "testville")

    kwargs = knowledge.search.call_args.kwargs
    assert kwargs["max_results"] == hybrid.CANDIDATES_PER_SEARCH
    assert kwargs["filters"] == filters


def test_empty_knowledge_base_gives_no_keyword_results(monkeypatch):
    hybrid._keyword_index.cache_clear()
    monkeypatch.setattr(hybrid, "_load_documents", lambda db_url, table, destination: [])

    assert hybrid.keyword_search("anything", "postgresql://fake", "t", None) == []


@pytest.mark.parametrize(
    ("mode", "search_type"),
    [(None, None), ("vector", None), ("agno_hybrid", "hybrid")],
)
def test_search_mode_selects_how_knowledge_is_searched(monkeypatch, mode, search_type):
    if mode:
        monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", mode)
    else:
        monkeypatch.delenv("KNOWLEDGE_SEARCH_MODE", raising=False)
    knowledge = _knowledge([])

    retrieval_service._search_knowledge(knowledge, "query", 5)

    assert knowledge.search.call_args.kwargs.get("search_type") == search_type


def test_search_mode_bm25_rrf_uses_the_hybrid_search(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", "bm25_rrf")
    with patch.object(retrieval_service, "hybrid_search", return_value=[]) as fused:
        retrieval_service._search_knowledge(_knowledge([]), "query", 5, "testville")

    fused.assert_called_once()
    assert fused.call_args.args[4] == "testville"


def test_unknown_search_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", "nonsense")

    with pytest.raises(ValueError, match="KNOWLEDGE_SEARCH_MODE"):
        retrieval_service._search_knowledge(_knowledge([]), "query", 5)
