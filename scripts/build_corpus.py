"""
Build the knowledge-base corpus in data/knowledge/ (never committed).

Usage:
    python scripts/build_corpus.py pin --destination <city> --state <state> --page <title> [--subpages]
    python scripts/build_corpus.py download
    python scripts/build_corpus.py build [--chunk-size N] [--overlap N]

Which pages make up the corpus is private too, so this script names none of them:
"pin" records a page's current revision in data/knowledge/sources.yaml and its
attribution in data/knowledge/SOURCES.md. Both files live only in the private
repository (docs/evaluation.md, "What is published"). "download" fetches exactly
the pinned revisions into data/knowledge/raw/, and fails for a page rather than
take a newer revision. "build" downloads what is missing and writes the JSONL.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT_DIR / "data" / "knowledge"
RAW_DIR = KNOWLEDGE_DIR / "raw"
SOURCES_PATH = KNOWLEDGE_DIR / "sources.yaml"
ATTRIBUTION_PATH = KNOWLEDGE_DIR / "SOURCES.md"

API_URL = "https://en.wikivoyage.org/w/api.php"
PAGE_URL = "https://en.wikivoyage.org/wiki/"
LICENCE = "CC BY-SA 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
USER_AGENT = "Agno-Travel-Agent-corpus-build/1.0 (https://github.com/yutingwang999/Agno_Travel_Agent)"
REQUEST_PAUSE_SECONDS = 1.0

HANDWRITTEN_PATH = KNOWLEDGE_DIR / "v1" / "source_documents.json"
HANDWRITTEN_SOURCE = "handwritten"
AUSTRALIA_WIDE_DESTINATION = "Australia"

# Characters. A starting point: task 4.5 compares chunk sizes on the evaluation dataset.
DEFAULT_CHUNK_SIZE = 800
DEFAULT_OVERLAP = 80

INTRODUCTION_SECTION = "Introduction"
DEFAULT_TOPIC = "general"
SECTION_TOPICS = {
    "See": "sights",
    "Do": "activities",
    "Eat": "food",
    "Drink": "nightlife",
    "Buy": "shopping",
    "Sleep": "accommodation",
    "Get in": "transport",
    "Get around": "transport",
    "Go next": "nearby",
    "Understand": "overview",
    INTRODUCTION_SECTION: "overview",
    "Stay safe": "practical",
    "Stay healthy": "practical",
    "Connect": "practical",
    "Cope": "practical",
}

LISTING_TEMPLATES = {"see", "do", "eat", "drink", "buy", "sleep", "listing", "go"}
LISTING_FIELDS = (
    ("address", "Address"),
    ("directions", "Directions"),
    ("hours", "Hours"),
    ("price", "Price"),
    ("checkin", "Check-in"),
    ("checkout", "Check-out"),
)
# Inline templates that hold a value in the sentence: name -> how to write their last argument.
INLINE_TEMPLATES = {
    "c": "{}°C",
    "km": "{} km",
    "feet": "{} ft",
    "acre": "{} acres",
    "aud": "A${}",
    "rint": "{}",
    "aur": "{}",
    "iata": "{}",
    "flag": "{}",
    "phone": "{}",
}
NON_TEXT_LINK_PREFIXES = ("file:", "image:", "category:")

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
REF_TAG = re.compile(r"<ref\b[^>]*/>|<ref\b.*?</ref>", re.S | re.I)
WIKI_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[https?://[^\s\]]+(?:\s+([^\]]*))?\]")
TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
NAMED_ARGUMENT = re.compile(r"\s*([A-Za-z][\w-]*)\s*=(.*)", re.S)
WIKI_TABLE = re.compile(r"^\{\|.*?^\|\}\s*$", re.S | re.M)
LINE_BREAK_TAG = re.compile(r"<br\s*/?>", re.I)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
LIST_MARKER = re.compile(r"^[*:#;]+\s*")
SPACES = re.compile(r"[ \t]+")
SECTION_HEADING = re.compile(r"^==\s*([^=].*?)\s*==$")
SUBHEADING = re.compile(r"^===+\s*(.*?)\s*===+$")


def api_get(**params) -> dict:
    """One MediaWiki API request, parsed; the caller paces its requests."""
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def page_url(title: str) -> str:
    return PAGE_URL + urllib.parse.quote(title.replace(" ", "_"), safe="/:_")


def load_sources(path: Path = SOURCES_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"{path} not found. The source list is private: copy it from the private "
            'repository (docs/evaluation.md, "What is published").'
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]


def write_attribution(sources: list[dict], path: Path = ATTRIBUTION_PATH) -> None:
    lines = [
        "# Knowledge corpus: sources and attribution",
        "",
        f"Text from Wikivoyage contributors, licensed under [{LICENCE}]({LICENCE_URL}).",
        "Cleaned and split into chunks; each chunk records its source page.",
        "",
        "| Page | Revision | Downloaded |",
        "| --- | --- | --- |",
    ]
    for source in sources:
        permalink = f"{source['url']}?oldid={source['revision']}"
        lines.append(f"| [{source['title']}]({permalink}) | {source['revision']} | {source['downloaded']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def pin(destination: str, state: str, page: str, subpages: bool) -> None:
    """Record the current revision of a page (and its subpages) in sources.yaml."""
    titles = [page]
    if subpages:
        listing = api_get(
            action="query", list="allpages", apprefix=f"{page}/", aplimit="50", apfilterredir="nonredirects"
        )
        titles += sorted(item["title"] for item in listing["query"]["allpages"])

    sources = load_sources() if SOURCES_PATH.exists() else []
    known = {source["title"] for source in sources}
    today = date.today().isoformat()
    for title in titles:
        if title in known:
            print(f"  [skip] {title} is already pinned")
            continue
        time.sleep(REQUEST_PAUSE_SECONDS)
        info = api_get(action="query", prop="revisions", rvprop="ids", titles=title)["query"]["pages"][0]
        sources.append(
            {
                "title": title,
                "destination": destination.lower(),
                "state": state,
                "revision": info["revisions"][0]["revid"],
                "url": page_url(title),
                "licence": LICENCE,
                "downloaded": today,
            }
        )
        print(f"  [pin] {title} at revision {sources[-1]['revision']}")

    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_PATH.write_text(
        yaml.safe_dump({"sources": sources}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    write_attribution(sources)


def raw_path(source: dict) -> Path:
    return RAW_DIR / f"{source['revision']}.wikitext"


def download(sources: list[dict]) -> None:
    """Fetch every pinned revision not yet in raw/; a page that cannot be fetched is an error."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for source in sources:
        path = raw_path(source)
        if path.exists():
            continue
        time.sleep(REQUEST_PAUSE_SECONDS)
        pages = api_get(
            action="query", prop="revisions", rvprop="ids|content", rvslots="main", revids=source["revision"]
        )["query"].get("pages", [])
        revisions = pages[0].get("revisions", []) if pages else []
        if not revisions or revisions[0]["revid"] != source["revision"] or "content" not in revisions[0]["slots"]["main"]:
            raise SystemExit(
                f"Revision {source['revision']} of {source['title']!r} is not available. "
                "Replace the source as a recorded corpus change; a newer revision is not taken silently."
            )
        path.write_text(revisions[0]["slots"]["main"]["content"], encoding="utf-8", newline="\n")
        print(f"  [download] {source['title']} ({source['revision']})")


def _template_args(body: str) -> tuple[str, list[str], dict[str, str]]:
    """Split a template body into its lowercase name, positional and named arguments."""
    name, *parts = body.split("|")
    positional: list[str] = []
    named: dict[str, str] = {}
    for part in parts:
        match = NAMED_ARGUMENT.match(part)
        if match:
            named[match.group(1).lower()] = match.group(2).strip()
        elif part.strip():
            positional.append(part.strip())
    return name.strip().lower(), positional, named


def _render_listing(named: dict[str, str]) -> str:
    """One line for a see / do / eat / ... listing, keeping what a traveller can use."""
    head = named.get("name", "")
    if named.get("alt"):
        head += f" ({named['alt']})"
    fields = [f"{label}: {named[key]}" for key, label in LISTING_FIELDS if named.get(key)]
    body = ". ".join(fields)
    text = ". ".join(part for part in (head, body, named.get("content", "")) if part)
    # Marks the line as a listing until clean_wikitext strips list markers.
    return f"\n* {text}\n"


def _render_template(match: re.Match) -> str:
    name, positional, named = _template_args(match.group(1))
    if name in LISTING_TEMPLATES:
        return _render_listing(named)
    if name == "marker":
        return named.get("name", "")
    if name == "time":
        return "–".join(positional)
    if name in INLINE_TEMPLATES and positional:
        return INLINE_TEMPLATES[name].format(positional[-1])
    if name.endswith("pricerange"):
        return "Price ranges: " + " / ".join(positional)
    return ""


def _replace_until_stable(pattern: re.Pattern, replacement, text: str) -> str:
    """Apply a pattern for an innermost construct until nested ones are resolved too."""
    while True:
        text, count = pattern.subn(replacement, text)
        if not count:
            return text


def _render_link(match: re.Match) -> str:
    target, _, label = match.group(1).partition("|")
    if target.strip().lower().startswith(NON_TEXT_LINK_PREFIXES):
        return ""
    return label or target


def clean_wikitext(text: str) -> str:
    """Turn wikitext into plain lines, leaving == section == headings in place."""
    text = HTML_COMMENT.sub("", text)
    text = REF_TAG.sub("", text)
    text = _replace_until_stable(WIKI_LINK, _render_link, text)
    text = EXTERNAL_LINK.sub(lambda m: m.group(1) or "", text)
    text = _replace_until_stable(TEMPLATE, _render_template, text)
    text = WIKI_TABLE.sub("", text)
    text = LINE_BREAK_TAG.sub(" ", text)
    text = HTML_TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")

    lines = []
    for line in text.splitlines():
        line = LIST_MARKER.sub("", line)
        line = SPACES.sub(" ", line).strip()
        subheading = SUBHEADING.match(line)
        lines.append(f"{subheading.group(1)}:" if subheading else line)
    return "\n".join(line for line in lines if line)


def split_sections(cleaned: str) -> list[tuple[str, str]]:
    """Return (section heading, body) pairs in page order; empty sections are dropped."""
    sections: list[tuple[str, str]] = []
    heading = INTRODUCTION_SECTION
    body: list[str] = []
    for line in cleaned.splitlines():
        match = SECTION_HEADING.match(line)
        if match:
            sections.append((heading, "\n".join(body)))
            heading, body = match.group(1), []
        else:
            body.append(line)
    sections.append((heading, "\n".join(body)))
    return [(name, text) for name, text in sections if _has_content(text)]


def _has_content(text: str) -> bool:
    """False for a section that holds only sub-heading lines ("Museums:")."""
    return any(not line.endswith(":") for line in text.splitlines())


def _tail(text: str, size: int) -> str:
    """The last ``size`` characters of a text, starting at a word boundary."""
    if size <= 0 or len(text) <= size:
        return text if size > 0 else ""
    tail = text[-size:]
    return tail.partition(" ")[2] or tail


def _split_long_line(line: str, chunk_size: int, overlap: int) -> list[str]:
    """Cut a line longer than a chunk at word boundaries, overlapping the pieces."""
    pieces = []
    start = 0
    while len(line) - start > chunk_size:
        end = line.rfind(" ", start + 1, start + chunk_size)
        end = end if end > start + overlap else start + chunk_size
        pieces.append(line[start:end].strip())
        start = end - overlap if overlap else end
        while overlap and start > 0 and line[start - 1] != " " and start < end:
            start += 1
    pieces.append(line[start:].strip())
    return pieces


def _split_trailing_heading(text: str) -> tuple[str, str]:
    """Separate a sub-heading line at the end of a text, so it can stay with what it introduces."""
    body, _, last = text.rpartition("\n")
    return (body, last) if last.endswith(":") else (text, "")


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split a section into chunks along its lines, the last resort being a fixed length.

    A new chunk starts with the last ``overlap`` characters of the previous one.
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk size")
    if len(text) <= chunk_size:
        return [text]

    lines: list[str] = []
    for line in text.splitlines():
        lines += [line] if len(line) <= chunk_size else _split_long_line(line, chunk_size, overlap)

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        current, heading = _split_trailing_heading(current)
        if current:
            chunks.append(current)
        # Longest start that fits: previous tail + sub-heading + line, then without the tail.
        starts = ("\n".join(filter(None, (_tail(current, overlap), heading, line))), f"{heading}\n{line}")
        current = next((start for start in starts if len(start) <= chunk_size), line)
    current, _ = _split_trailing_heading(current)
    if current:
        chunks.append(current)
    return chunks


def chunk_id(source: str, section: str, sequence: int) -> str:
    """Stable identifier: the same source, section and position always give the same id."""
    return hashlib.sha256(f"{source}\n{section}\n{sequence}".encode()).hexdigest()[:16]


def _chunks_of_document(
    text: str,
    *,
    destination: str,
    state: str | None,
    title: str,
    source: str,
    section: str,
    topic: str,
    chunk_size: int,
    overlap: int,
) -> list[dict]:
    return [
        {
            "chunk_id": chunk_id(source, f"{title}\n{section}", sequence),
            "destination": destination,
            "state": state,
            "topic": topic,
            "title": title,
            "chunk_text": chunk_text,
            "source": source,
            "section": section,
        }
        for sequence, chunk_text in enumerate(split_text(text, chunk_size, overlap))
    ]


def page_chunks(source: dict, wikitext: str, chunk_size: int, overlap: int) -> list[dict]:
    """Every chunk of one downloaded page."""
    chunks: list[dict] = []
    for section, text in split_sections(clean_wikitext(wikitext)):
        chunks += _chunks_of_document(
            text,
            destination=source["destination"],
            state=source["state"],
            title=source["title"],
            source=source["url"],
            section=section,
            topic=SECTION_TOPICS.get(section, DEFAULT_TOPIC),
            chunk_size=chunk_size,
            overlap=overlap,
        )
    return chunks


def handwritten_chunks(chunk_size: int, overlap: int, path: Path = HANDWRITTEN_PATH) -> list[dict]:
    """The Australia-wide documents of corpus v1; the v1 city guides are replaced by the pages."""
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Corpus v1 is private: copy it from the private "
            'repository (docs/evaluation.md, "What is published").'
        )
    documents = json.loads(path.read_text(encoding="utf-8"))
    chunks: list[dict] = []
    for document in documents:
        if document["destination"] != AUSTRALIA_WIDE_DESTINATION:
            continue
        chunks += _chunks_of_document(
            document["chunk_text"],
            destination=AUSTRALIA_WIDE_DESTINATION.lower(),
            state=None,
            title=document["title"],
            source=HANDWRITTEN_SOURCE,
            section=document["title"],
            topic=document["metadata_json"]["category"],
            chunk_size=chunk_size,
            overlap=overlap,
        )
    return chunks


def corpus_path(chunk_size: int, overlap: int) -> Path:
    return KNOWLEDGE_DIR / f"corpus_c{chunk_size}_o{overlap}.jsonl"


def build(sources: list[dict], chunk_size: int, overlap: int) -> Path:
    """Write the JSONL for one chunking configuration; same inputs, same bytes."""
    download(sources)
    chunks = handwritten_chunks(chunk_size, overlap)
    for source in sources:
        chunks += page_chunks(source, raw_path(source).read_text(encoding="utf-8"), chunk_size, overlap)

    path = corpus_path(chunk_size, overlap)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"Wrote {len(chunks)} chunks to {path.relative_to(ROOT_DIR)}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    pin_parser = commands.add_parser("pin", help="record a page's current revision")
    pin_parser.add_argument("--destination", required=True)
    pin_parser.add_argument("--state", required=True)
    pin_parser.add_argument("--page", required=True)
    pin_parser.add_argument("--subpages", action="store_true")
    commands.add_parser("download", help="fetch the pinned revisions")
    build_parser = commands.add_parser("build", help="write the JSONL for a chunking configuration")
    build_parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    build_parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()

    if args.command == "pin":
        pin(args.destination, args.state, args.page, args.subpages)
    elif args.command == "download":
        download(load_sources())
    else:
        build(load_sources(), args.chunk_size, args.overlap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
