"""Judge calibration: manual scores recorded against the judge's own output, and agreement.

A reviewer goes through the judge's verdicts for a stratified sample instead of
re-extracting everything from scratch (see docs/evaluation.md, "Judge calibration"):

- at least 20 itineraries; in each, every claim the judge called supported, up to
  ``UNSUPPORTED_PER_ITINERARY`` of the claims it called unsupported, and up to
  ``PLACES_PER_ITINERARY`` places;
- plus every itinerary of the run with a place the judge put outside the destination,
  for the destination check only (``destination_only``), so both of the judge's
  answers get reviewed.

The reviewer marks each item: for a claim, is it one of the four claim kinds
(``is_claim``) and is it supported by the knowledge context (``supported``); for a
place, is it in the destination (``in_destination``); claims the judge missed go in
``missed_claims``. The answers are written in a Markdown review sheet
(``eval/calibration/<run id>.review.md``, see :func:`render_review`) and stored as one
JSON object per itinerary in ``eval/calibration/<run id>.jsonl``.

Because the sample is stratified, agreement is reported per stratum (per judge
answer), never pooled into one rate.

Public API::

    from evaluation.calibration import agreement, load_scores, stratified_template
"""

import json
import random
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

MIN_SAMPLE = 20
UNSUPPORTED_PER_ITINERARY = 5
PLACES_PER_ITINERARY = 4
# Below this, improve the judge prompt before trusting the judge's numbers.
MIN_AGREEMENT = 0.8


class ClaimScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    category: str | None = None  # the judge's category, shown for reference
    judge_supported: bool
    is_claim: bool | None = None  # None until reviewed
    supported: bool | None = None  # may be left out when is_claim is false


class PlaceScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    judge_in_destination: bool
    in_destination: bool | None = None  # None until reviewed


class ItineraryScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    # True for itineraries added only to review the judge's "outside the destination" answers.
    destination_only: bool = False
    claims: list[ClaimScore] = Field(default_factory=list)
    missed_claims: list[str] = Field(default_factory=list)
    places: list[PlaceScore] = Field(default_factory=list)


def load_scores(path: Path) -> list[ItineraryScore]:
    scores = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                scores.append(ItineraryScore.model_validate(json.loads(line)))
            except ValueError as exc:
                raise ValueError(f"{path.name} line {number}: {exc}") from exc
    return scores


def stratified_template(entry_id: str, faithfulness_verdict: dict, destination_verdict: dict,
                        rng: random.Random) -> ItineraryScore:
    """A blank score record for one sampled itinerary, pre-filled with the judge's verdicts."""
    claims = faithfulness_verdict.get("claims", [])
    supported = [c for c in claims if c["supported"]]
    unsupported = [c for c in claims if not c["supported"]]
    chosen_unsupported = rng.sample(unsupported, min(UNSUPPORTED_PER_ITINERARY, len(unsupported)))
    places = destination_verdict.get("places", [])
    chosen_places = rng.sample(places, min(PLACES_PER_ITINERARY, len(places)))
    keep_claims = {id(c) for c in supported + chosen_unsupported}
    keep_places = {id(p) for p in chosen_places}
    return ItineraryScore(
        entry_id=entry_id,
        claims=[ClaimScore(text=c["text"], category=c["category"], judge_supported=c["supported"])
                for c in claims if id(c) in keep_claims],  # original order
        places=[PlaceScore(name=p["name"], judge_in_destination=p["in_destination"])
                for p in places if id(p) in keep_places],
    )


def destination_only_template(entry_id: str, destination_verdict: dict) -> ItineraryScore:
    """A record reviewing every place the judge put outside the destination."""
    return ItineraryScore(
        entry_id=entry_id,
        destination_only=True,
        places=[PlaceScore(name=p["name"], judge_in_destination=False)
                for p in destination_verdict.get("places", []) if not p["in_destination"]],
    )


def unreviewed_items(scores: list[ItineraryScore]) -> list[str]:
    """Labels of claims and places the reviewer has not filled in yet."""
    missing = []
    for itinerary in scores:
        missing += [f"{itinerary.entry_id} claim {i}" for i, c in enumerate(itinerary.claims, 1)
                    if c.is_claim is None or (c.is_claim and c.supported is None)]
        missing += [f"{itinerary.entry_id} place {i}" for i, p in enumerate(itinerary.places, 1)
                    if p.in_destination is None]
    return missing


def agreement(scores: list[ItineraryScore]) -> dict:
    """Judge–human agreement, per stratum, for faithfulness and the destination check.

    Raises ValueError while any sampled item is still unreviewed.
    """
    unreviewed = unreviewed_items(scores)
    if unreviewed:
        raise ValueError(f"{len(unreviewed)} item(s) not reviewed yet, e.g. {unreviewed[:3]}")

    claims = [c for s in scores for c in s.claims]
    accepted = [c for c in claims if c.is_claim]
    places = [p for s in scores for p in s.places]
    faithfulness_scores = [s for s in scores if not s.destination_only]
    return {
        "sample_size": len(faithfulness_scores),
        "sample_meets_minimum": len(faithfulness_scores) >= MIN_SAMPLE,
        "destination_only_itineraries": len(scores) - len(faithfulness_scores),
        "faithfulness": {
            # Of the claims the judge called supported, how many the reviewer also calls supported.
            "judge_supported": _stratum([c.supported for c in accepted if c.judge_supported], True),
            "judge_unsupported": _stratum([c.supported for c in accepted if not c.judge_supported], False),
        },
        # Of the sampled items the judge extracted, the share that really are claims.
        "extraction_precision": len(accepted) / len(claims) if claims else None,
        "claims_reviewed": len(claims),
        "missed_claims": sum(len(s.missed_claims) for s in scores),
        "destination": {
            "judge_in": _stratum([p.in_destination for p in places if p.judge_in_destination], True),
            "judge_out": _stratum([p.in_destination for p in places if not p.judge_in_destination], False),
        },
        "min_agreement": MIN_AGREEMENT,
    }


# --- Review sheet: one Markdown file to read and fill in --------------------------------

_YES, _NO, _SKIP, _OPEN = "y", "n", "-", "?"
_CLAIM_LINE = re.compile(r"^c(\d+)\s+\[claim:\s*(\S)\]\s+\[supported:\s*(\S)\]")
_PLACE_LINE = re.compile(r"^p(\d+)\s+\[in:\s*(\S)\]")
_ENTRY_LINE = re.compile(r"^## (\S+)")
_MISSED_LINE = re.compile(r"^missed:(.*)$")


def _mark(value: bool | None) -> str:
    return _OPEN if value is None else (_YES if value else _NO)


def render_review(run_id: str, scores: list[ItineraryScore], records: dict[str, dict]) -> str:
    """The review sheet: every sampled item with an answer slot, plus what is needed to decide it.

    *records* maps entry id to its results.jsonl record. Existing answers in *scores*
    are carried over; ``supported`` is pre-filled ``n`` when there was no knowledge
    context, since no claim can be supported then.
    """
    lines = [f"# Judge calibration review: `{run_id}`", "",
             "Replace each `?` with `y` or `n` (`supported` is `-` when the item is not a claim), "
             "add missed claims after `missed:` separated by `;`, then run "
             f"`python scripts/eval_calibration.py score {run_id}`.",
             "Rules: docs/evaluation.md, \"Judge calibration\" → \"How to review\". "
             "Decide `supported` only from the knowledge context shown here, never from what you know "
             "about the place; decide `in` with your own geographic knowledge.", ""]
    for score in scores:
        record = records[score.entry_id]
        faith, place = record["judge"]["faithfulness"], record["judge"]["destination"]
        form = record["form"]
        reasons = {p["name"]: p["reason"] for p in place["verdict"]["places"]}
        suffix = " (destination check only)" if score.destination_only else ""
        lines += [f"## {score.entry_id}{suffix}", "",
                  f"Request: {form['destination']}, {form['trip_length']} days, {form['budget']}, "
                  f"\"{form['travel_style']}\"" + (f" · notes: {form['notes']}" if form.get("notes") else ""), ""]
        if not score.destination_only:
            lines += ["**Knowledge context the generator was given**", "", "```",
                      faith["knowledge_context"] or "(none: every claim is unsupported by definition)", "```", ""]
        lines += ["**Itinerary**", "", "```", faith["itinerary_text"], "```", ""]
        no_context = not faith["knowledge_context"]
        if not score.destination_only:
            lines += ["**Claims**", ""]
            for i, c in enumerate(score.claims, 1):
                supported = _mark(c.supported)
                if c.supported is None and no_context:
                    supported = _NO
                verdict = "SUPPORTED" if c.judge_supported else "unsupported"
                lines.append(f"c{i}  [claim: {_mark(c.is_claim)}] [supported: {supported}]   "
                             f"judge: {verdict} · {c.category} · {c.text}")
            others = _unsampled_claims(faith["verdict"]["claims"], score.claims)
            if others:
                lines += ["", "*Also extracted by the judge (not sampled, no answer needed; "
                          "a claim in neither list is a missed claim):*", ""]
                lines += [f"- {c['category']} · {c['text']}" for c in others]
            lines += ["", "missed: " + "; ".join(score.missed_claims), ""]
        lines += ["**Places**", ""]
        for i, p in enumerate(score.places, 1):
            verdict = "in" if p.judge_in_destination else "OUTSIDE"
            lines.append(f"p{i}  [in: {_mark(p.in_destination)}]   judge: {verdict} · {p.name} — "
                         f"{reasons.get(p.name, '')}")
        lines.append("")
    return "\n".join(lines)


def _unsampled_claims(all_claims: list[dict], sampled: list[ClaimScore]) -> list[dict]:
    """The judge's claims that are not in the sample, in the judge's order."""
    remaining = [(c.text, c.category) for c in sampled]
    others = []
    for claim in all_claims:
        key = (claim["text"], claim["category"])
        if key in remaining:
            remaining.remove(key)
        else:
            others.append(claim)
    return others


def parse_review(text: str, scores: list[ItineraryScore]) -> list[ItineraryScore]:
    """Copy the answers in a filled-in review sheet onto *scores* (returned as new objects).

    Raises ValueError naming the line of any answer that is not y / n / - / ?.
    """
    by_id = {s.entry_id: s.model_copy(deep=True) for s in scores}
    current: ItineraryScore | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if match := _ENTRY_LINE.match(line):
            current = by_id.get(match.group(1))
            if current is None:
                raise ValueError(f"line {number}: unknown entry {match.group(1)!r}")
        elif current is None:
            continue
        elif match := _CLAIM_LINE.match(line):
            claim = _item(current.claims, int(match.group(1)), number)
            claim.is_claim = _answer(match.group(2), number, allow_skip=False)
            claim.supported = _answer(match.group(3), number, allow_skip=True)
        elif match := _PLACE_LINE.match(line):
            place = _item(current.places, int(match.group(1)), number)
            place.in_destination = _answer(match.group(2), number, allow_skip=False)
        elif match := _MISSED_LINE.match(line):
            current.missed_claims = [m.strip() for m in match.group(1).split(";") if m.strip()]
    return [by_id[s.entry_id] for s in scores]


def _item(items: list, index: int, line: int):
    if not 1 <= index <= len(items):
        raise ValueError(f"line {line}: item {index} does not exist")
    return items[index - 1]


def _answer(token: str, line: int, allow_skip: bool) -> bool | None:
    token = token.lower()
    if token == _YES:
        return True
    if token == _NO:
        return False
    if token == _OPEN or (allow_skip and token == _SKIP):
        return None
    raise ValueError(f"line {line}: answer {token!r} must be y, n{', -' if allow_skip else ''} or ?")


def _stratum(human_labels: list[bool], judge_label: bool) -> dict:
    agree = [label == judge_label for label in human_labels]
    return {"compared": len(agree), "agreement": sum(agree) / len(agree) if agree else None}
