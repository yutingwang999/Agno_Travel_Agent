"""Evaluation dataset: entry format, loading and coverage check.

The dataset lives in ``eval/dataset.jsonl`` (one JSON object per line) and its
versions in ``eval/dataset_meta.json``::

    {"dataset_version": 1, "corpus_version": "v1"}

Each entry carries the structured ``form`` that drives the current system and a
free-text ``utterance`` of the same request; see :class:`DatasetEntry`.

Public API::

    from evaluation.dataset import check_dataset, load_dataset, load_meta

    entries = load_dataset()          # raises DatasetError on malformed lines
    problems = check_dataset(entries, load_meta())
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.workflow.config import DAILY_COST_CAP_AUD_PER_PERSON

ROOT_DIR = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT_DIR / "eval" / "dataset.jsonl"
META_PATH = ROOT_DIR / "eval" / "dataset_meta.json"

ExpectedBehavior = Literal["plan", "refuse", "clarify"]

BUDGET_LEVELS = ("budget", "moderate", "luxury")
REQUIRED_TAGS = (
    "contradictory",
    "out_of_scope",
    "prompt_injection",
    "mixed_language",
    "chinese_destination",
)
NOTES_MAX_LENGTH = 500

MIN_ENTRIES = 50
MAX_ENTRIES = 100
# "Several destinations / a range of trip lengths / several styles", made concrete.
MIN_DISTINCT_DESTINATIONS = 5
MIN_DISTINCT_TRIP_LENGTHS = 3
MIN_DISTINCT_TRAVEL_STYLES = 5

# A form destination in a mixed_language entry must be an English place name;
# one in a chinese_destination entry must be written in Chinese characters.
_ENGLISH_PLACE_NAME = re.compile(r"^[A-Za-z][A-Za-z .'-]*$")
_CHINESE_PLACE_NAME = re.compile(r"^[一-鿿]+$")

# Sections that relevant_sections may point at, per corpus version.
# v1: the 13 handwritten v0.1.0 documents in scripts/seed.py, source "handwritten",
# section = document title.
CORPUS_SECTIONS: dict[str, set[tuple[str, str]]] = {
    "v1": {
        ("handwritten", title)
        for title in (
            "Guide to Sydney",
            "Guide to Melbourne",
            "Guide to the Gold Coast",
            "Guide to Brisbane",
            "Australia's Sporting Experiences",
            "Best Places to See Wild Koalas",
            "Australia's Seasonal Nature Experiences",
            "Family Adventure Travel in Australia",
            "Girls Getaway Destinations in Australia",
            "Australia's Best Street Art",
            "Australia's Historical and Cultural Experiences",
            "Guided Indigenous Walking Tours",
            "Australia's Best Seafood Experiences",
        )
    },
}


class DatasetError(Exception):
    """Raised when the dataset or its metadata cannot be loaded."""


class RequestForm(BaseModel):
    """The form fields sent to ``POST /generate``.

    Deliberately not :class:`app.workflow.intake_model.TravelRequest`: some
    entries carry invalid input on purpose (expected to be rejected with 422).

    ``notes`` holds request details the four form fields cannot express. v0.1.0
    ignores it (``TravelRequest`` drops unknown fields); ``rebuild-rag`` adds it
    to the request, so the same inputs measure the change.
    """

    model_config = ConfigDict(extra="forbid")

    destination: str
    trip_length: int
    budget: str
    travel_style: str
    notes: str | None = Field(default=None, min_length=1, max_length=NOTES_MAX_LENGTH)
    # Daily budget per person in whole AUD, excluding accommodation; sent with the
    # request, and it sets the budget constraint's ceiling even for a system that
    # ignores the field (harden-workflow-guardrails).
    max_daily_budget_aud: int | None = Field(default=None, ge=1)


class GoldSlots(BaseModel):
    """What a request parser should extract from ``utterance``."""

    model_config = ConfigDict(extra="forbid")

    destination: str | None = None
    trip_length_days: int | None = None
    budget: Literal["budget", "moderate", "luxury"] | None = None
    preferences: list[str] = Field(default_factory=list)


class RelevantSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    section: str


class DatasetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tags: list[str]
    form: RequestForm
    utterance: str = Field(min_length=1)
    gold_slots: GoldSlots
    expected_behavior: ExpectedBehavior
    relevant_sections: list[RelevantSection]
    # False marks a plan entry that needs no knowledge-base content at all.
    needs_knowledge: bool = True
    # Optional; reserved for a later fact-coverage metric.
    expected_facts: list[str] | None = None


class DatasetMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: int = Field(ge=1)
    corpus_version: str


def load_dataset(path: Path = DATASET_PATH) -> list[DatasetEntry]:
    """Load and validate every line of a JSONL dataset file."""
    entries: list[DatasetEntry] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DatasetError(f"cannot read {path}: {exc}") from exc

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(DatasetEntry.model_validate(json.loads(line)))
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: invalid JSON ({exc.msg})")
        except ValidationError as exc:
            errors.append(f"line {number}: {_format_validation_error(exc)}")

    if errors:
        raise DatasetError("; ".join(errors))
    return entries


def load_meta(path: Path = META_PATH) -> DatasetMeta:
    try:
        return DatasetMeta.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise DatasetError(f"cannot load {path}: {exc}") from exc


def check_dataset(
    entries: list[DatasetEntry],
    meta: DatasetMeta,
    min_entries: int = MIN_ENTRIES,
    max_entries: int = MAX_ENTRIES,
) -> list[str]:
    """Return every coverage or labelling problem found; an empty list means it passes."""
    problems: list[str] = []

    if not min_entries <= len(entries) <= max_entries:
        problems.append(f"dataset has {len(entries)} entries, expected {min_entries}-{max_entries}")

    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            problems.append(f"duplicate id {entry.id!r}")
        seen.add(entry.id)

    all_tags = {tag for entry in entries for tag in entry.tags}
    for tag in REQUIRED_TAGS:
        if tag not in all_tags:
            problems.append(f"no entry tagged {tag!r}")

    budgets = {entry.form.budget for entry in entries}
    for level in BUDGET_LEVELS:
        if level not in budgets:
            problems.append(f"no entry with budget {level!r}")

    plan_entries = [entry for entry in entries if entry.expected_behavior == "plan"]
    for label, values, minimum in (
        ("destinations", {e.form.destination.strip().lower() for e in plan_entries},
         MIN_DISTINCT_DESTINATIONS),
        ("trip lengths", {e.form.trip_length for e in plan_entries}, MIN_DISTINCT_TRIP_LENGTHS),
        ("travel styles", {e.form.travel_style.strip().lower() for e in plan_entries},
         MIN_DISTINCT_TRAVEL_STYLES),
    ):
        if len(values) < minimum:
            problems.append(f"plan entries cover {len(values)} {label}, expected at least {minimum}")

    # Entries with their own daily budget amount (harden-workflow-guardrails): one per
    # level, and one whose amount is above its level's default ceiling.
    with_amount = [e for e in entries if e.form.max_daily_budget_aud is not None]
    for level in BUDGET_LEVELS:
        if not any(e.form.budget == level for e in with_amount):
            problems.append(f"no entry with budget {level!r} and max_daily_budget_aud")
    if not any(
        e.form.budget in DAILY_COST_CAP_AUD_PER_PERSON
        and e.form.max_daily_budget_aud > DAILY_COST_CAP_AUD_PER_PERSON[e.form.budget]
        for e in with_amount
    ):
        problems.append("no entry whose max_daily_budget_aud is above its level's default")

    if not any("out_of_scope" in e.tags and e.expected_behavior == "refuse" for e in entries):
        problems.append("no out_of_scope entry expecting refuse (e.g. a non-Australian city)")

    known_sections = CORPUS_SECTIONS.get(meta.corpus_version)
    if known_sections is None:
        problems.append(f"unknown corpus version {meta.corpus_version!r}")

    for entry in entries:
        problems.extend(_check_entry(entry, known_sections))

    return problems


def _check_entry(entry: DatasetEntry, known_sections: set[tuple[str, str]] | None) -> list[str]:
    problems: list[str] = []
    where = f"entry {entry.id!r}"

    if "mixed_language" in entry.tags and not _ENGLISH_PLACE_NAME.match(entry.form.destination):
        problems.append(f"{where}: mixed_language form.destination must be an English place name")

    if "chinese_destination" in entry.tags and not _CHINESE_PLACE_NAME.match(entry.form.destination):
        problems.append(f"{where}: chinese_destination form.destination must be a Chinese place name")

    if "prompt_injection" in entry.tags and entry.expected_behavior != "refuse":
        problems.append(f"{where}: prompt_injection entries must expect 'refuse'")

    if entry.expected_behavior == "plan":
        # gold_slots holds only what the utterance states; a plannable request always
        # names where and how long, while the budget may go unsaid (null).
        slots = entry.gold_slots
        if slots.destination is None or slots.trip_length_days is None:
            problems.append(f"{where}: plan entries need gold_slots destination and trip_length_days")
        if entry.needs_knowledge and not entry.relevant_sections:
            problems.append(f"{where}: plan entry has no relevant_sections and is not marked needs_knowledge=false")

    if not entry.needs_knowledge and entry.relevant_sections:
        problems.append(f"{where}: needs_knowledge=false but relevant_sections is not empty")

    if known_sections is not None:
        for section in entry.relevant_sections:
            if (section.source, section.section) not in known_sections:
                problems.append(f"{where}: unknown section ({section.source!r}, {section.section!r})")

    return problems


def _format_validation_error(exc: ValidationError) -> str:
    return ", ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
