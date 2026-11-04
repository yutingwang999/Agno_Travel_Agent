"""scripts/build_corpus.py: cleaning, splitting, chunk ids, determinism.

All text here is made up: corpus text is never committed. No network access.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = {
    "title": "Testville/Old Town",
    "destination": "testville",
    "state": "Tasmania",
    "revision": 123,
    "url": "https://example.org/wiki/Testville/Old_Town",
}

WIKITEXT = """{{pagebanner|Testville banner.jpg}}
'''Testville''' is a [[made-up place|made-up]] town. [[File:Harbour.jpg|thumb|A [[harbour]] view]]

==Understand==
The summer reaches {{c|31}} and the airport ({{IATA|TVL}}) is {{km|12}} away.<ref>A note</ref><!-- hidden -->

==See==
===Museums===
* {{see
| name=Museum of Testing | alt=MoT | url=https://example.org | email=
| address=1 Fake St | lat=-42.8 | long=147.3 | directions=near the [[Old Town|old town]]
| phone=+61 3 0000 0000 | tollfree=
| hours=10AM-5PM | price={{AUD|10}}
| lastedit=2020-01-01
| content=A fictional museum. See [https://example.org the website].
}}

==Districts==
{{Regionlist|region1name=North}}
"""


@pytest.fixture(scope="module")
def corpus():
    path = Path(__file__).parent.parent / "scripts" / "build_corpus.py"
    spec = importlib.util.spec_from_file_location("build_corpus_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_wikitext_keeps_prose_and_drops_markup(corpus):
    cleaned = corpus.clean_wikitext(WIKITEXT)

    assert "Testville is a made-up town." in cleaned
    for leftover in ("{{", "}}", "[[", "]]", "'''", "<ref", "hidden", "banner.jpg", "Harbour.jpg"):
        assert leftover not in cleaned


def test_clean_wikitext_keeps_values_held_in_inline_templates(corpus):
    cleaned = corpus.clean_wikitext(WIKITEXT)

    assert "The summer reaches 31°C and the airport (TVL) is 12 km away." in cleaned


def test_clean_wikitext_renders_a_listing_with_its_useful_fields(corpus):
    cleaned = corpus.clean_wikitext(WIKITEXT)

    assert (
        "Museum of Testing (MoT). Address: 1 Fake St. Directions: near the old town. "
        "Hours: 10AM-5PM. Price: A$10. A fictional museum. See the website." in cleaned
    )
    for dropped in ("-42.8", "+61 3", "2020-01-01", "https://example.org"):
        assert dropped not in cleaned


def test_split_sections_follows_level_two_headings_and_drops_empty_ones(corpus):
    sections = dict(corpus.split_sections(corpus.clean_wikitext(WIKITEXT)))

    assert list(sections) == ["Introduction", "Understand", "See"]
    assert sections["See"].startswith("Museums:\n")


def test_section_with_only_a_subheading_is_dropped(corpus):
    assert corpus.split_sections("==Do==\nWalks:") == []


def test_short_text_stays_one_chunk(corpus):
    assert corpus.split_text("short text", 100, 10) == ["short text"]


def test_long_section_splits_along_lines_within_the_size(corpus):
    lines = [f"Line number {i} of the section." for i in range(30)]

    chunks = corpus.split_text("\n".join(lines), 200, 0)

    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert "\n".join(chunks).splitlines() == lines


def test_next_chunk_starts_with_the_end_of_the_previous_one(corpus):
    lines = [f"Line number {i} of the section." for i in range(30)]

    chunks = corpus.split_text("\n".join(lines), 200, 40)

    assert len(chunks) > 1
    for previous, following in zip(chunks, chunks[1:]):
        carried = following.splitlines()[0]
        assert previous.endswith(carried)
        assert 0 < len(carried) <= 40


def test_sub_heading_stays_with_the_text_it_introduces(corpus):
    filler = "A sentence that fills the chunk up nicely here."
    text = "\n".join([filler, filler, "Beaches:", "The first beach is long and sandy."])

    chunks = corpus.split_text(text, 110, 0)

    assert chunks[-1] == "Beaches:\nThe first beach is long and sandy."
    assert not any(chunk.endswith("Beaches:") for chunk in chunks)


def test_sub_heading_at_the_end_of_a_long_section_is_dropped(corpus):
    filler = "A sentence that fills the chunk up nicely here."

    chunks = corpus.split_text("\n".join([filler, filler, filler, "Beaches:"]), 110, 0)

    assert "\n".join(chunks).splitlines() == [filler, filler, filler]


def test_line_longer_than_a_chunk_is_cut_at_word_boundaries_with_overlap(corpus):
    words = [f"word{i}" for i in range(200)]

    chunks = corpus.split_text(" ".join(words), 100, 20)

    assert all(len(chunk) <= 100 for chunk in chunks)
    joined = " ".join(chunks).split()
    assert set(joined) == set(words)  # every word survives, none is cut in two
    assert len(joined) > len(words)  # and some appear twice: the overlap


def test_overlap_not_smaller_than_chunk_size_is_rejected(corpus):
    with pytest.raises(ValueError):
        corpus.split_text("x" * 50, 10, 10)


def test_chunk_id_is_stable_and_depends_on_source_section_and_position(corpus):
    assert corpus.chunk_id("s", "See", 0) == corpus.chunk_id("s", "See", 0)
    assert len({corpus.chunk_id("s", "See", 0), corpus.chunk_id("s", "Eat", 0),
                corpus.chunk_id("t", "See", 0), corpus.chunk_id("s", "See", 1)}) == 4


def test_page_chunks_carry_the_metadata_of_their_page_and_section(corpus):
    chunks = corpus.page_chunks(SOURCE, WIKITEXT, 800, 80)

    see = next(chunk for chunk in chunks if chunk["section"] == "See")
    assert set(see) == {"chunk_id", "destination", "state", "topic", "title", "chunk_text", "source", "section"}
    assert see["destination"] == "testville"
    assert see["state"] == "Tasmania"
    assert see["topic"] == "sights"
    assert see["title"] == "Testville/Old Town"
    assert see["source"] == SOURCE["url"]


def test_same_section_on_two_pages_of_one_source_gets_different_ids(corpus):
    other = {**SOURCE, "title": "Testville/New Town"}

    ids = {chunk["chunk_id"] for chunk in corpus.page_chunks(SOURCE, WIKITEXT, 800, 80)}
    other_ids = {chunk["chunk_id"] for chunk in corpus.page_chunks(other, WIKITEXT, 800, 80)}

    assert not ids & other_ids


def test_handwritten_chunks_take_only_the_australia_wide_documents(corpus, tmp_path):
    path = tmp_path / "source_documents.json"
    path.write_text(
        json.dumps(
            [
                {"destination": "Testville", "title": "Guide", "chunk_text": "City.",
                 "metadata_json": {"source": "handwritten", "category": "destination"}},
                {"destination": "Australia", "title": "Made-up Topic", "chunk_text": "National.",
                 "metadata_json": {"source": "handwritten", "category": "nature"}},
            ]
        ),
        encoding="utf-8",
    )

    chunks = corpus.handwritten_chunks(800, 80, path)

    assert [chunk["title"] for chunk in chunks] == ["Made-up Topic"]
    assert chunks[0]["destination"] == "australia"
    assert chunks[0]["state"] is None
    assert chunks[0]["source"] == "handwritten"
    assert chunks[0]["section"] == "Made-up Topic"
    assert chunks[0]["topic"] == "nature"


def test_missing_private_files_stop_with_a_clear_message(corpus, tmp_path):
    with pytest.raises(SystemExit, match="private"):
        corpus.load_sources(tmp_path / "sources.yaml")
    with pytest.raises(SystemExit, match="private"):
        corpus.handwritten_chunks(800, 80, tmp_path / "source_documents.json")


def test_build_twice_gives_identical_bytes(corpus, tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(corpus, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(corpus, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(corpus, "HANDWRITTEN_PATH", tmp_path / "source_documents.json")
    monkeypatch.setattr(corpus, "handwritten_chunks", lambda size, overlap: [])
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "123.wikitext").write_text(WIKITEXT, encoding="utf-8")

    first = corpus.build([SOURCE], 100, 10).read_bytes()
    second = corpus.build([SOURCE], 100, 10).read_bytes()

    assert first and first == second


def test_fixture_takes_national_documents_and_a_few_chunks_per_section(corpus):
    def chunk(destination, section):
        return {"destination": destination, "section": section}

    chunks = (
        [chunk("australia", "Made-up Topic")] * 3
        + [chunk("sydney", "Eat")] * 5
        + [chunk("sydney", "Get in")]
        + [chunk("hobart", "Eat")]
    )

    selected = corpus.select_fixture(chunks)

    assert selected.count(chunk("australia", "Made-up Topic")) == 3
    assert selected.count(chunk("sydney", "Eat")) == corpus.FIXTURE_CHUNKS_PER_SECTION
    assert chunk("sydney", "Get in") not in selected
    assert chunk("hobart", "Eat") not in selected


def test_download_refuses_a_revision_the_wiki_no_longer_has(corpus, tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "RAW_DIR", tmp_path)
    monkeypatch.setattr(corpus, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(corpus, "api_get", lambda **params: {"query": {"badrevids": {"123": {}}}})

    with pytest.raises(SystemExit, match="not available"):
        corpus.download([SOURCE])
    assert not list(tmp_path.iterdir())
