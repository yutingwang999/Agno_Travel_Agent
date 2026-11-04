"""Corpus v1 lives in a private local file, not in scripts/seed.py.

The tests use made-up documents: corpus text is never committed.
"""

import importlib.util
import json
import os
from pathlib import Path

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


def test_load_source_documents_reads_the_local_file(seed_module, tmp_path):
    documents = [{"destination": "Testville", "title": "T", "chunk_text": "Made up.", "metadata_json": {}}]
    path = tmp_path / "source_documents.json"
    path.write_text(json.dumps(documents), encoding="utf-8")

    assert seed_module.load_source_documents(str(path)) == documents


def test_missing_corpus_file_warns_and_returns_nothing(seed_module, tmp_path, capsys):
    """A clone without the private file still seeds and runs, with an empty knowledge base."""
    assert seed_module.load_source_documents(str(tmp_path / "missing.json")) == []
    assert "[warn] corpus file not found" in capsys.readouterr().out


def test_seed_script_contains_no_corpus_text():
    source = (Path(__file__).parent.parent / "scripts" / "seed.py").read_text(encoding="utf-8")

    assert "SOURCE_DOCUMENTS = [" not in source
    assert "chunk_text" not in source.split("def load_source_documents")[0]
