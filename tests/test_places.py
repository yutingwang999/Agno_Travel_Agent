"""harden-workflow-guardrails task 5.1: the Australian place list."""

import json
from pathlib import Path

import pytest

from app.workflow.places import PLACE_LIST_PATH, canonical_destination, load_place_list

ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def places() -> dict[str, str]:
    return load_place_list()


def _dataset() -> list[dict]:
    with (ROOT_DIR / "eval" / "dataset.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_dataset_destinations_to_plan_are_listed(places):
    """Spec scenario "Dataset destinations covered", English and Chinese."""
    missing = [
        e["form"]["destination"]
        for e in _dataset()
        if e["expected_behavior"] == "plan" and canonical_destination(e["form"]["destination"], places) is None
    ]
    assert missing == []


def test_chinese_dataset_destinations_map_to_english(places):
    for entry in _dataset():
        if "chinese_destination" in entry["tags"]:
            canonical = canonical_destination(entry["form"]["destination"], places)
            assert canonical is not None and canonical.isascii(), entry["id"]


def test_knowledge_base_destinations_are_listed(places):
    """Every city the seeded corpus covers ("Australia" is the general documents)."""
    for city in ("Sydney", "Melbourne", "Brisbane", "Gold Coast"):
        assert canonical_destination(city, places) == city.lower()


@pytest.mark.parametrize("name", ["Paris", "Tokyo", "Auckland", "Bali", "London", "Australia", "澳大利亚", "澳洲"])
def test_foreign_cities_and_the_country_are_not_listed(places, name):
    assert canonical_destination(name, places) is None


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("Sydney", "sydney"),
        ("  Gold   Coast ", "gold coast"),
        ("墨爾本", "melbourne"),                 # Traditional script
        ("Sydney, NSW", "sydney"),               # state suffix
        ("Hobart Tasmania", "hobart"),
        ("Perth, WA, Australia", "perth"),       # several qualifiers
        ("Tasmania", "tasmania"),                # state name
        ("Ayers Rock", "uluru"),                 # other name
        ("the east coast", None),
        ("somewhere warm", None),
        ("part", None),                          # GeoNames alternate name of Perth, not used
    ],
)
def test_lookup(places, destination, expected):
    assert canonical_destination(destination, places) == expected


def test_place_list_header_and_sorting():
    lines = PLACE_LIST_PATH.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "name\tcanonical\tsource"
    names = [line.split("\t")[0] for line in lines[1:]]
    assert names == sorted(names) and len(names) == len(set(names))


@pytest.mark.skipif(
    not (ROOT_DIR / "data" / "places" / "raw" / "cities1000.txt").exists(),
    reason="GeoNames download not present (data/places/SOURCES.md)",
)
def test_rebuild_gives_the_committed_file():
    """Rebuilding from the same inputs reproduces australia.tsv exactly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_places", ROOT_DIR / "scripts" / "build_places.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = load_place_list()
    rebuilt = {name: canonical for name, (canonical, _) in module.build().items()}
    assert rebuilt == committed
