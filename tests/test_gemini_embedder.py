"""GeminiEmbedder: task types per caller and the document embedding cache. No API calls."""

import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agno.knowledge.document.base import Document

from app.workflow.gemini_embedder import (
    TASK_TYPE_DOCUMENT,
    TASK_TYPE_QUERY,
    TASK_TYPE_SEMANTIC,
    GeminiEmbedder,
)


def _fake_client():
    client = MagicMock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])
    return client


def _embedder(**kwargs) -> GeminiEmbedder:
    with patch("app.workflow.gemini_embedder.genai.Client", return_value=_fake_client()):
        return GeminiEmbedder(api_key="fake", **kwargs)


def _task_types(client) -> list[str]:
    return [call.kwargs["config"].task_type for call in client.models.embed_content.call_args_list]


def test_query_uses_the_query_task_type():
    embedder = _embedder()

    assert embedder.get_embedding("beaches") == [0.1, 0.2]
    assert _task_types(embedder._client) == [TASK_TYPE_QUERY]


def test_document_embedded_through_agno_uses_the_document_task_type():
    """Agno embeds a document through Document.embed, not through get_embedding."""
    embedder = _embedder()

    document = Document(content="A chunk of text.")
    document.embed(embedder=embedder)

    assert document.embedding == [0.1, 0.2]
    assert _task_types(embedder._client) == [TASK_TYPE_DOCUMENT]


def test_async_document_embedding_uses_the_document_task_type():
    embedder = _embedder()

    document = Document(content="A chunk of text.")
    asyncio.run(document.async_embed(embedder=embedder))

    assert _task_types(embedder._client) == [TASK_TYPE_DOCUMENT]


def test_second_embedding_of_a_document_comes_from_the_cache(tmp_path):
    embedder = _embedder(cache_dir=tmp_path)

    first, _ = embedder.get_embedding_and_usage("A chunk.")
    second, _ = embedder.get_embedding_and_usage("A chunk.")

    assert first == second == [0.1, 0.2]
    assert embedder._client.models.embed_content.call_count == 1


def test_cache_survives_a_new_embedder(tmp_path):
    _embedder(cache_dir=tmp_path).get_embedding_and_usage("A chunk.")

    fresh = _embedder(cache_dir=tmp_path)
    fresh.get_embedding_and_usage("A chunk.")

    fresh._client.models.embed_content.assert_not_called()


@pytest.mark.parametrize(
    "other",
    [
        {"model": "other-model"},
        {"document_task_type": TASK_TYPE_SEMANTIC},
    ],
)
def test_cache_is_separate_per_model_and_task_type(tmp_path, other):
    _embedder(cache_dir=tmp_path).get_embedding_and_usage("A chunk.")

    different = _embedder(cache_dir=tmp_path, **other)
    different.get_embedding_and_usage("A chunk.")

    different._client.models.embed_content.assert_called_once()


def test_different_text_is_not_a_cache_hit(tmp_path):
    embedder = _embedder(cache_dir=tmp_path)

    embedder.get_embedding_and_usage("A chunk.")
    embedder.get_embedding_and_usage("Another chunk.")

    assert embedder._client.models.embed_content.call_count == 2


def test_queries_are_never_cached(tmp_path):
    embedder = _embedder(cache_dir=tmp_path)

    embedder.get_embedding("beaches")
    embedder.get_embedding("beaches")

    assert embedder._client.models.embed_content.call_count == 2
    assert not list(tmp_path.rglob("*.json"))


def test_cache_write_leaves_no_temporary_files(tmp_path):
    _embedder(cache_dir=tmp_path).get_embedding_and_usage("A chunk.")

    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize(
    ("profile", "query", "document"),
    [
        (None, TASK_TYPE_QUERY, TASK_TYPE_DOCUMENT),
        ("retrieval", TASK_TYPE_QUERY, TASK_TYPE_DOCUMENT),
        ("semantic", TASK_TYPE_SEMANTIC, TASK_TYPE_SEMANTIC),
    ],
)
def test_build_knowledge_selects_task_types_by_profile(monkeypatch, profile, query, document):
    from app.workflow import knowledge_base

    if profile:
        monkeypatch.setenv("KNOWLEDGE_TASK_TYPES", profile)
    else:
        monkeypatch.delenv("KNOWLEDGE_TASK_TYPES", raising=False)
    with (
        patch.object(knowledge_base, "PgVector") as fake_pgvector,
        patch.object(knowledge_base, "Knowledge"),
    ):
        knowledge_base.build_knowledge(db_url="postgresql://fake", api_key="fake-key")

    embedder = fake_pgvector.call_args.kwargs["embedder"]
    assert (embedder.query_task_type, embedder.document_task_type) == (query, document)
    assert embedder.cache_dir is None


def test_unknown_task_type_profile_is_rejected(monkeypatch):
    from app.workflow import knowledge_base

    monkeypatch.setenv("KNOWLEDGE_TASK_TYPES", "nonsense")
    with pytest.raises(ValueError, match="KNOWLEDGE_TASK_TYPES"):
        knowledge_base.knowledge_task_types()


def test_intent_classification_keeps_semantic_similarity():
    """The 50 category vectors depend on it; they are not re-embedded."""
    from app.workflow import cag_matcher

    client = _fake_client()
    with patch.object(cag_matcher.genai, "Client", return_value=client):
        cag_matcher._compute_embedding("family trip", "fake", "gemini-embedding-001")

    assert _task_types(client) == [TASK_TYPE_SEMANTIC]


def test_seed_embeds_categories_with_semantic_similarity():
    path = Path(__file__).parent.parent / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_embedding_under_test", path)
    seed = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "unused"))
        spec.loader.exec_module(seed)

    client = _fake_client()
    with patch.object(seed, "_genai_client", client):
        seed.compute_embedding("a category")

    assert _task_types(client) == [TASK_TYPE_SEMANTIC]


def test_v1_evaluation_configs_keep_the_task_types_their_table_was_embedded_with():
    from evaluation.runner import load_config

    for name in ("v010-baseline", "harden-workflow-guardrails"):
        assert load_config(name).embedding_task_types == "semantic"
