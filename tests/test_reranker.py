"""rebuild-rag step d: Cross-Encoder reranking and its fallback. All text is made up; the model is mocked."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agno.knowledge.document.base import Document

from app.workflow import hybrid_search as hybrid
from app.workflow import reranker, retrieval_service


def _document(chunk_id: str) -> Document:
    return Document(name="Testville", content=f"Made up text {chunk_id}.", meta_data={"chunk_id": chunk_id})


DOCUMENTS = [_document(chunk_id) for chunk_id in ("a", "b", "c")]


def _ids(documents) -> list[str]:
    return [document.meta_data["chunk_id"] for document in documents]


def _model(scores) -> MagicMock:
    model = MagicMock()
    model.predict.return_value = scores
    return model


def test_documents_are_ordered_by_score():
    with patch.object(reranker, "_load_model", return_value=_model([0.1, 0.9, 0.5])):
        assert _ids(reranker.rerank("query", DOCUMENTS, 3)) == ["b", "c", "a"]


def test_result_is_cut_to_top_k():
    with patch.object(reranker, "_load_model", return_value=_model([0.1, 0.9, 0.5])):
        assert _ids(reranker.rerank("query", DOCUMENTS, 2)) == ["b", "c"]


def test_equal_scores_keep_the_candidate_order():
    with patch.object(reranker, "_load_model", return_value=_model([0.5, 0.5, 0.5])):
        assert _ids(reranker.rerank("query", DOCUMENTS, 3)) == ["a", "b", "c"]


def test_the_model_scores_the_query_with_each_chunk_text():
    model = _model([0.1, 0.2, 0.3])
    with patch.object(reranker, "_load_model", return_value=model):
        reranker.rerank("query", DOCUMENTS, 3)

    assert model.predict.call_args.args[0] == [("query", document.content) for document in DOCUMENTS]


def test_load_failure_keeps_the_order_before_reranking():
    """Spec scenario "Reranker unavailable"."""
    with patch.object(reranker, "_load_model", side_effect=OSError("no model")):
        assert _ids(reranker.rerank("query", DOCUMENTS, 2)) == ["a", "b"]


def test_scoring_failure_keeps_the_order_before_reranking():
    model = MagicMock()
    model.predict.side_effect = RuntimeError("scoring failed")
    with patch.object(reranker, "_load_model", return_value=model):
        assert _ids(reranker.rerank("query", DOCUMENTS, 2)) == ["a", "b"]


def test_no_candidates_do_not_load_the_model():
    with patch.object(reranker, "_load_model") as load:
        assert reranker.rerank("query", [], 5) == []

    load.assert_not_called()


def test_the_model_defaults_to_the_cpu(monkeypatch):
    monkeypatch.delenv("RERANK_DEVICE", raising=False)
    monkeypatch.delenv("RERANK_MODEL", raising=False)
    with patch.object(reranker, "_load_model", return_value=_model([0.1, 0.2, 0.3])) as load:
        reranker.rerank("query", DOCUMENTS, 3)

    load.assert_called_once_with(reranker.DEFAULT_RERANK_MODEL, "cpu")


def _knowledge(vector_results: list[Document]) -> MagicMock:
    knowledge = MagicMock()
    knowledge.vector_db = SimpleNamespace(db_url="postgresql://fake", table_name="t")
    knowledge.search.return_value = vector_results
    return knowledge


def test_vector_rerank_scores_the_vector_candidates(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", "vector_rerank")
    knowledge = _knowledge(DOCUMENTS)
    with patch.object(retrieval_service, "rerank", return_value=DOCUMENTS[:1]) as scored:
        chunks = retrieval_service._search_knowledge(knowledge, "query", 5)

    assert knowledge.search.call_args.kwargs["max_results"] == hybrid.CANDIDATES_PER_SEARCH
    assert scored.call_args.args == ("query", DOCUMENTS, 5)
    assert len(chunks) == 1


def test_fused_rerank_scores_every_candidate_of_both_searches_in_fused_order(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", "bm25_rrf_rerank")
    keyword_only = _document("keyword-only")
    monkeypatch.setattr(hybrid, "keyword_search", lambda *args: [DOCUMENTS[1], keyword_only])
    with patch.object(retrieval_service, "rerank", return_value=[]) as scored:
        retrieval_service._search_knowledge(_knowledge(DOCUMENTS), "query", 2, "testville")

    # b is in both rankings, so it leads the order a failed reranker would keep.
    assert _ids(scored.call_args.args[1]) == ["b", "a", "keyword-only", "c"]
    assert scored.call_args.args[2] == 2


def test_hybrid_search_is_the_fused_order_cut_to_top_k(monkeypatch):
    monkeypatch.setattr(hybrid, "keyword_search", lambda *args: [DOCUMENTS[1]])

    results = hybrid.hybrid_search(_knowledge(DOCUMENTS), "query", 2, None, None)

    assert _ids(results) == ["b", "a"]


@pytest.mark.parametrize("mode", ["vector_rerank", "bm25_rrf_rerank"])
def test_a_reranking_failure_still_returns_chunks(monkeypatch, mode):
    """Spec requirement "Reranking failure fallback", through the search."""
    monkeypatch.setenv("KNOWLEDGE_SEARCH_MODE", mode)
    monkeypatch.setattr(hybrid, "keyword_search", lambda *args: [])
    with patch.object(reranker, "_load_model", side_effect=OSError("no model")):
        chunks = retrieval_service._search_knowledge(_knowledge(DOCUMENTS), "query", 2)

    assert len(chunks) == 2
