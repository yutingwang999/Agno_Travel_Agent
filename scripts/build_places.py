"""
Build data/places/australia.tsv, the destination guard's place list.

Usage:
    python scripts/build_places.py

Inputs (see data/places/SOURCES.md):
  - data/places/raw/cities1000.txt  GeoNames, downloaded by hand (not in git)
  - data/places/states.tsv          states and territories, with abbreviations
  - data/places/destinations.tsv    tourist destinations that are not towns, and their nicknames
  - data/places/chinese.tsv         Chinese names (Simplified and Traditional script)

From GeoNames only the Australian rows are used, and only their primary name and
ASCII name: alternate names include romanisations from other languages ("part"
and "pet" for Perth, "gold" for Gold Coast) that would let non-place input pass.
A hand-kept name wins over a GeoNames one; between GeoNames places with the same
name the most populous one gives the canonical name. The output is sorted, so
re-running on the same inputs gives an identical file.
"""

import csv
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

from app.workflow.places import PLACE_LIST_PATH, normalize_name  # noqa: E402

PLACES_DIR = ROOT_DIR / "data" / "places"
GEONAMES_PATH = PLACES_DIR / "raw" / "cities1000.txt"
HAND_LISTS = ("states.tsv", "destinations.tsv", "chinese.tsv")

# Column positions in the GeoNames "geoname" table (readme.txt of the dump).
NAME, ASCIINAME, COUNTRY_CODE, POPULATION = 1, 2, 8, 14


def geonames_names(path: Path) -> dict[str, tuple[str, int]]:
    """Accepted name -> (canonical name, population) for Australian GeoNames rows."""
    names: dict[str, tuple[str, int]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row[COUNTRY_CODE] != "AU":
                continue
            canonical = normalize_name(row[NAME])
            population = int(row[POPULATION] or 0)
            for name in {normalize_name(row[NAME]), normalize_name(row[ASCIINAME])}:
                if name and (name not in names or population > names[name][1]):
                    names[name] = (canonical, population)
    return names


def hand_names(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            normalize_name(row["name"]): normalize_name(row["canonical"])
            for row in csv.DictReader(handle, delimiter="\t")
        }


def build() -> dict[str, tuple[str, str]]:
    """Accepted name -> (canonical name, source)."""
    places = {name: (canonical, "geonames") for name, (canonical, _) in geonames_names(GEONAMES_PATH).items()}
    for filename in HAND_LISTS:
        source = filename.removesuffix(".tsv")
        for name, canonical in hand_names(PLACES_DIR / filename).items():
            places[name] = (canonical, source)
    return places


def main() -> int:
    if not GEONAMES_PATH.exists():
        sys.exit(f"ERROR: {GEONAMES_PATH.relative_to(ROOT_DIR)} not found; see data/places/SOURCES.md")
    places = build()
    with PLACE_LIST_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["name", "canonical", "source"])
        for name in sorted(places):
            writer.writerow([name, *places[name]])
    counts: dict[str, int] = {}
    for _, source in places.values():
        counts[source] = counts.get(source, 0) + 1
    print(f"wrote {PLACE_LIST_PATH.relative_to(ROOT_DIR)}: {len(places)} names {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
