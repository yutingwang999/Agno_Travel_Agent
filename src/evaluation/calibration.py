"""Judge calibration: manual scores recorded against the judge's own output, and agreement.

A reviewer goes through the judge's verdicts for a sample of itineraries (at least
20) and, instead of re-extracting claims from scratch, marks each judged item:

- each faithfulness claim: is it really one of the four claim kinds (``is_claim``),
  and is it supported by the knowledge context (``supported``)?
- each destination place: is it really in the destination (``in_destination``)?
- claims the judge missed are listed in ``missed_claims``.

One JSON object per itinerary in a JSONL file (``eval/calibration/<run id>.jsonl``)::

    {"entry_id": "e026",
     "claims": [{"text": "Austin Lane", "judge_supported": true, "is_claim": true, "supported": true}],
     "missed_claims": ["opens at 4pm"],
     "places": [{"name": "Austin Lane", "judge_in_destination": true, "in_destination": true}]}

Agreement is the share of items where the reviewer's label equals the judge's,
over claims the reviewer accepts as claims (``is_claim``) and over all places.

Public API::

    from evaluation.calibration import agreement, load_scores
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

MIN_SAMPLE = 20


class ClaimScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    judge_supported: bool
    is_claim: bool
    supported: bool | None = None  # may be left out when is_claim is false


class PlaceScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    judge_in_destination: bool
    in_destination: bool


class ItineraryScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
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


def agreement(scores: list[ItineraryScore]) -> dict:
    """Judge–human agreement for faithfulness and for the destination check.

    Raises ValueError when a claim the reviewer accepts has no ``supported`` label.
    """
    accepted, rejected = [], 0
    for itinerary in scores:
        for claim in itinerary.claims:
            if not claim.is_claim:
                rejected += 1
                continue
            if claim.supported is None:
                raise ValueError(f"{itinerary.entry_id}: claim {claim.text!r} has no 'supported' label")
            accepted.append(claim.judge_supported == claim.supported)
    places = [p.judge_in_destination == p.in_destination for s in scores for p in s.places]
    extracted = len(accepted) + rejected
    return {
        "sample_size": len(scores),
        "sample_meets_minimum": len(scores) >= MIN_SAMPLE,
        "faithfulness_agreement": _rate(accepted),
        "claims_compared": len(accepted),
        # How well the judge extracts claims, reported beside the agreement rate.
        "extraction_precision": len(accepted) / extracted if extracted else None,
        "missed_claims": sum(len(s.missed_claims) for s in scores),
        "destination_agreement": _rate(places),
        "places_compared": len(places),
    }


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None
