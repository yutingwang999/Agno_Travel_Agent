"""build-evaluation-harness: stratified manual-score sampling and judge–human agreement."""

import json
import random

import pytest

from evaluation.calibration import (
    PLACES_PER_ITINERARY,
    UNSUPPORTED_PER_ITINERARY,
    ItineraryScore,
    agreement,
    destination_only_template,
    load_scores,
    stratified_template,
    unreviewed_items,
)


def _claim(judge, is_claim=True, human=None):
    return {"text": "x", "category": "named_place", "judge_supported": judge, "is_claim": is_claim,
            "supported": human}


def _place(judge, human):
    return {"name": "p", "judge_in_destination": judge, "in_destination": human}


def _score(entry_id="e001", claims=(), places=(), missed=(), destination_only=False):
    return ItineraryScore.model_validate({"entry_id": entry_id, "destination_only": destination_only,
                                          "claims": list(claims), "places": list(places),
                                          "missed_claims": list(missed)})


def test_stratified_template_keeps_all_supported_and_samples_the_rest():
    claims = ([{"category": "named_place", "text": f"s{i}", "supported": True} for i in range(3)]
              + [{"category": "price", "text": f"u{i}", "supported": False} for i in range(12)])
    places = [{"name": f"p{i}", "in_destination": True, "reason": "r"} for i in range(9)]
    score = stratified_template("e1", {"claims": claims}, {"places": places}, random.Random(0))

    assert sum(c.judge_supported for c in score.claims) == 3
    assert sum(not c.judge_supported for c in score.claims) == UNSUPPORTED_PER_ITINERARY
    assert len(score.places) == PLACES_PER_ITINERARY
    assert all(c.is_claim is None and c.supported is None for c in score.claims)
    texts = [c.text for c in score.claims]
    assert texts == sorted(texts, key=lambda t: [c["text"] for c in claims].index(t))  # original order


def test_stratified_template_with_few_items_takes_them_all():
    score = stratified_template("e1", {"claims": [{"category": "price", "text": "u", "supported": False}]},
                                {"places": []}, random.Random(0))
    assert len(score.claims) == 1 and score.places == []


def test_destination_only_template_keeps_only_outside_places():
    verdict = {"places": [{"name": "a", "in_destination": True, "reason": ""},
                          {"name": "b", "in_destination": False, "reason": "far"}]}
    score = destination_only_template("e2", verdict)
    assert score.destination_only and score.claims == []
    assert [p.name for p in score.places] == ["b"]


def test_agreement_reported_per_stratum():
    scores = [
        _score(claims=[_claim(True, human=True), _claim(True, human=False), _claim(False, human=False),
                       _claim(False, is_claim=False)],
               places=[_place(True, True), _place(True, False)], missed=["opens at 4pm"]),
        _score("e002", claims=[_claim(False, human=True)], places=[_place(True, True)]),
        _score("e003", destination_only=True, places=[_place(False, False), _place(False, True)]),
    ]
    result = agreement(scores)

    assert result["sample_size"] == 2 and result["destination_only_itineraries"] == 1
    assert result["faithfulness"]["judge_supported"] == {"compared": 2, "agreement": 0.5}
    assert result["faithfulness"]["judge_unsupported"] == {"compared": 2, "agreement": 0.5}
    assert result["extraction_precision"] == pytest.approx(4 / 5)
    assert result["missed_claims"] == 1
    assert result["destination"]["judge_in"]["agreement"] == pytest.approx(2 / 3)
    assert result["destination"]["judge_out"] == {"compared": 2, "agreement": 0.5}
    assert result["sample_meets_minimum"] is False


def test_twenty_itineraries_meet_minimum_destination_only_ones_do_not_count():
    scores = [_score(f"e{i:03d}", claims=[_claim(True, human=True)]) for i in range(19)]
    scores.append(_score("x", destination_only=True, places=[_place(False, False)]))
    assert agreement(scores)["sample_meets_minimum"] is False
    scores.append(_score("e019", claims=[_claim(True, human=True)]))
    assert agreement(scores)["sample_meets_minimum"] is True


def test_unreviewed_items_block_scoring():
    blank = _score(claims=[{"text": "x", "judge_supported": True}], places=[_place(True, None)])
    assert unreviewed_items([blank]) == ["e001 claim 1", "e001 place 1"]
    with pytest.raises(ValueError, match="not reviewed yet"):
        agreement([blank])


def test_accepted_claim_without_supported_label_is_unreviewed():
    half = _score(claims=[_claim(True, is_claim=True, human=None)])
    assert unreviewed_items([half]) == ["e001 claim 1"]


def test_rejected_claim_needs_no_supported_label():
    result = agreement([_score(claims=[_claim(True, is_claim=False)])])
    assert result["faithfulness"]["judge_supported"] == {"compared": 0, "agreement": None}
    assert result["extraction_precision"] == 0.0


def _record(context="[Guide to Sydney]\nBondi ..."):
    return {"form": {"destination": "Sydney", "trip_length": 3, "budget": "moderate", "travel_style": "family"},
            "judge": {"faithfulness": {"knowledge_context": context, "itinerary_text": "Day 1: Bondi",
                                       "verdict": {"claims": []}},
                      "destination": {"verdict": {"places": [{"name": "Bondi", "in_destination": True,
                                                              "reason": "Sydney beach"}]}}}}


def test_review_sheet_round_trip():
    from evaluation.calibration import parse_review, render_review

    blank = _score(claims=[{"text": "Bondi", "category": "named_place", "judge_supported": True},
                           {"text": "free", "category": "price", "judge_supported": False}],
                   places=[{"name": "Bondi", "judge_in_destination": True}])
    sheet = render_review("run", [blank], {"e001": _record()})
    assert "c1  [claim: ?] [supported: ?]   judge: SUPPORTED · named_place · Bondi" in sheet
    assert "p1  [in: ?]   judge: in · Bondi — Sydney beach" in sheet

    filled = (sheet.replace("c1  [claim: ?] [supported: ?]", "c1  [claim: y] [supported: y]")
                   .replace("c2  [claim: ?] [supported: ?]", "c2  [claim: n] [supported: -]")
                   .replace("p1  [in: ?]", "p1  [in: Y]")
                   .replace("missed: ", "missed: opens at 9am; ferry 20 min"))
    scores = parse_review(filled, [blank])
    claims = scores[0].claims
    assert (claims[0].is_claim, claims[0].supported) == (True, True)
    assert (claims[1].is_claim, claims[1].supported) == (False, None)
    assert scores[0].places[0].in_destination is True
    assert scores[0].missed_claims == ["opens at 9am", "ferry 20 min"]
    assert blank.claims[0].is_claim is None  # the input is not modified
    assert agreement(scores)["faithfulness"]["judge_supported"] == {"compared": 1, "agreement": 1.0}


def test_review_sheet_carries_existing_answers_and_prefills_no_context():
    from evaluation.calibration import render_review

    partly = _score(claims=[{"text": "A", "category": "named_place", "judge_supported": False,
                             "is_claim": True, "supported": None}])
    sheet = render_review("run", [partly], {"e001": _record(context="")})
    assert "c1  [claim: y] [supported: n]" in sheet  # no context: supported can only be n
    assert "(none: every claim is unsupported by definition)" in sheet


def test_review_sheet_lists_unsampled_judge_claims_for_missed_checks():
    from evaluation.calibration import render_review

    record = _record()
    record["judge"]["faithfulness"]["verdict"] = {"claims": [
        {"category": "named_place", "text": "Bondi", "supported": True},
        {"category": "price", "text": "$10 ferry", "supported": False},
    ]}
    sampled = _score(claims=[{"text": "Bondi", "category": "named_place", "judge_supported": True}])
    sheet = render_review("run", [sampled], {"e001": record})
    assert "- price · $10 ferry" in sheet
    assert "- named_place · Bondi" not in sheet  # sampled claims are not repeated


def test_review_sheet_rejects_bad_answers():
    from evaluation.calibration import parse_review

    blank = _score(claims=[{"text": "A", "judge_supported": True}])
    with pytest.raises(ValueError, match=r"line 3: answer 'x'"):
        parse_review("# t\n## e001\nc1  [claim: x] [supported: ?]", [blank])
    with pytest.raises(ValueError, match="item 2 does not exist"):
        parse_review("## e001\nc2  [claim: y] [supported: y]", [blank])
    with pytest.raises(ValueError, match="unknown entry"):
        parse_review("## e999", [blank])


def test_load_scores_round_trip_and_bad_line(tmp_path):
    good = tmp_path / "run.jsonl"
    good.write_text(json.dumps(_score(claims=[_claim(True, human=True)]).model_dump()) + "\n", encoding="utf-8")
    assert load_scores(good)[0].entry_id == "e001"

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"entry_id": "e1", "claims": [{"text": "x"}]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_scores(bad)
