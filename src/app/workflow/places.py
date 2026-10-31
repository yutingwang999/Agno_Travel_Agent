"""Australian place list for the destination guard (harden-workflow-guardrails, decision 6).

``data/places/australia.tsv`` maps every accepted destination name — English
names and common Chinese names — to a canonical lowercase English name.  It is
built by ``scripts/build_places.py``; see ``data/places/SOURCES.md``.

Public API:
    normalize_name(text) -> str
    load_place_list(path) -> dict[str, str]
    canonical_destination(destination, places) -> str | None
"""

import csv
import re
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
PLACE_LIST_PATH = ROOT_DIR / "data" / "places" / "australia.tsv"

# Trailing qualifiers a user may add after a place: "Sydney, NSW", "Hobart Tasmania",
# "Perth, WA, Australia".  Tried only when the full name is not in the list.
_REGIONS = (
    "new south wales|nsw|victoria|vic|queensland|qld|south australia|sa|"
    "western australia|wa|tasmania|tas|northern territory|nt|"
    "australian capital territory|act|australia"
)
_TRAILING_REGION = re.compile(rf"^(?P<place>.+?)(?:\s*,\s*|\s+)(?:{_REGIONS})$")


def normalize_name(text: str) -> str:
    """Lowercase, strip and collapse inner whitespace."""
    return " ".join(text.split()).lower()


def load_place_list(path: Path = PLACE_LIST_PATH) -> dict[str, str]:
    """Read the place list: accepted name -> canonical name."""
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["name"]: row["canonical"] for row in csv.DictReader(handle, delimiter="\t")}


@lru_cache(maxsize=1)
def default_place_list() -> dict[str, str]:
    return load_place_list()


def canonical_destination(destination: str, places: dict[str, str] | None = None) -> str | None:
    """Return the canonical name of *destination*, or None if it is not an Australian place.

    The full normalised name is looked up first; failing that, trailing state,
    territory or country qualifiers are removed one at a time and the rest is
    looked up again ("Perth, WA, Australia" -> "perth").
    """
    places = default_place_list() if places is None else places
    name = normalize_name(destination)
    while name:
        if name in places:
            return places[name]
        match = _TRAILING_REGION.match(name)
        if match is None:
            return None
        name = match.group("place").rstrip(" ,")
    return None
