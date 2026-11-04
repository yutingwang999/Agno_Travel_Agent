"""Seeding from private local corpus files. Corpus text is never committed.

The tests use made-up documents; the database and Agno's vector store are faked.
"""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def seed_module():
    """scripts/seed.py loaded as a module (it reads GEMINI_API_KEY at import)."""
    path = Path(__file__).parent.parent / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_corpus_under_test", path)
    seed = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "unused"))
        spec.loader.exec_module(seed)
    return seed


def _chunk(chunk_id: str, text: str = "Made up.") -> dict:
    return {
        "chunk_id": chunk_id,
        "destination": "testville",
        "state": "Tasmania",
        "topic": "food",
        "title": "Testville",
        "chunk_text": text,
        "source": "https://example.org/wiki/Testville",
        "section": "Eat",
    }


def _write_corpus(path: Path, chunks: list[dict]) -> str:
    path.write_text("".join(json.dumps(chunk) + "\n" for chunk in chunks), encoding="utf-8")
    return str(path)


@pytest.fixture()
def vector_store(seed_module, monkeypatch):
    """A fake table: inserted documents are counted by the row check at the end of the seed."""
    store = MagicMock()
    store.inserted = []
    store.insert.side_effect = lambda checksum, documents: store.inserted.extend(documents)
    knowledge = MagicMock(vector_db=store)
    monkeypatch.setattr(seed_module, "build_knowledge", MagicMock(return_value=knowledge))
    monkeypatch.setattr(seed_module, "_seeded_chunks", lambda *args: -1)
    monkeypatch.setattr(seed_module, "_stored_with_embedding", lambda *args: len(store.inserted))
    return store


def test_load_source_documents_reads_the_local_file(seed_module, tmp_path):
    documents = [{"destination": "Testville", "title": "T", "chunk_text": "Made up.", "metadata_json": {}}]
    path = tmp_path / "source_documents.json"
    path.write_text(json.dumps(documents), encoding="utf-8")

    assert seed_module.load_source_documents(str(path)) == documents


def test_missing_corpus_v1_file_warns_and_returns_nothing(seed_module, tmp_path, capsys):
    """A clone without the private file still seeds and runs, with an empty knowledge base."""
    assert seed_module.load_source_documents(str(tmp_path / "missing.json")) == []
    assert "[warn] corpus file not found" in capsys.readouterr().out


def test_missing_corpus_warns_and_leaves_the_table_alone(seed_module, tmp_path, vector_store, capsys):
    seed_module.seed_corpus(str(tmp_path / "missing.jsonl"))

    assert "[warn] corpus file not found" in capsys.readouterr().out
    vector_store.drop.assert_not_called()
    vector_store.insert.assert_not_called()


def test_chunks_are_inserted_with_their_metadata(seed_module, tmp_path, vector_store):
    seed_module.seed_corpus(_write_corpus(tmp_path / "corpus.jsonl", [_chunk("a"), _chunk("b", "Other.")]))

    first = vector_store.inserted[0]
    assert [d.id for d in vector_store.inserted] == ["a", "b"]
    assert first.name == "Testville"
    assert first.content == "Made up."
    for key in ("chunk_id", "destination", "state", "topic", "source", "section"):
        assert first.meta_data[key] == _chunk("a")[key]


def test_table_already_holding_the_corpus_is_left_alone_before_any_embedding(
    seed_module, tmp_path, vector_store, monkeypatch
):
    """Spec scenario "Re-running seed"."""
    path = _write_corpus(tmp_path / "corpus.jsonl", [_chunk("a"), _chunk("b", "Other.")])
    monkeypatch.setattr(seed_module, "_seeded_chunks", lambda *args: 2)

    seed_module.seed_corpus(path)

    seed_module.build_knowledge.reset_mock()
    seed_module.seed_corpus(path)
    seed_module.build_knowledge.assert_not_called()
    vector_store.drop.assert_not_called()
    vector_store.insert.assert_not_called()


def test_table_holding_something_else_is_rebuilt(seed_module, tmp_path, vector_store):
    """Spec scenario "Chunking configuration changed"."""
    vector_store.table_exists.return_value = True

    seed_module.seed_corpus(_write_corpus(tmp_path / "corpus.jsonl", [_chunk("new")]))

    vector_store.drop.assert_called_once()
    vector_store.create.assert_called_once()
    assert [d.id for d in vector_store.inserted] == ["new"]


def test_checksum_changes_with_the_corpus_text(seed_module, tmp_path):
    path = tmp_path / "corpus.jsonl"
    _, first = seed_module.load_corpus(_write_corpus(path, [_chunk("a", "One text.")]))
    _, second = seed_module.load_corpus(_write_corpus(path, [_chunk("a", "Another text.")]))

    assert first != second


def test_chunk_agno_failed_to_store_stops_the_seed(seed_module, tmp_path, vector_store, monkeypatch):
    """Agno logs a failed embedding and continues; the seed must not report success."""
    monkeypatch.setattr(seed_module, "_stored_with_embedding", lambda *args: 1)

    with pytest.raises(SystemExit, match="1 of 2 chunks"):
        seed_module.seed_corpus(_write_corpus(tmp_path / "corpus.jsonl", [_chunk("a"), _chunk("b", "Other.")]))


def test_knowledge_corpus_selects_what_is_seeded(seed_module, monkeypatch):
    v1, jsonl = MagicMock(), MagicMock()
    monkeypatch.setattr(seed_module, "seed_source_documents", v1)
    monkeypatch.setattr(seed_module, "seed_corpus", jsonl)

    monkeypatch.setenv("KNOWLEDGE_CORPUS", "v1")
    seed_module.seed_knowledge_base()
    v1.assert_called_once()
    jsonl.assert_not_called()

    monkeypatch.setenv("KNOWLEDGE_CORPUS", "tests/fixtures/knowledge/corpus.jsonl")
    seed_module.seed_knowledge_base()
    assert jsonl.call_args.args[0].endswith(os.path.join("tests/fixtures/knowledge/corpus.jsonl"))

    monkeypatch.delenv("KNOWLEDGE_CORPUS")
    seed_module.seed_knowledge_base()
    assert jsonl.call_args.args[0].endswith(seed_module.DEFAULT_CORPUS)


def test_seed_script_contains_no_corpus_text():
    source = (Path(__file__).parent.parent / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "SOURCE_DOCUMENTS = [" not in source
    assert "chunk_text" not in source.split("def load_source_documents")[0]
