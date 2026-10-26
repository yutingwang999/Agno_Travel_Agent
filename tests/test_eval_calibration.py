"""build-evaluation-harness: manual-score record format and judge–human agreement."""

import json

import pytest

from evaluation.calibration import ItineraryScore, agreement, load_scores


def _score(entry_id="e001", claims=(), places=(), missed=()):
    return ItineraryScore.model_validate({
        "entry_id": entry_id,
        "claims": list(claims),
        "missed_claims": list(missed),
        "places": list(places),
    })


def _claim(judge, human, is_claim=True):
    return {"text": "x", "judge_supported": judge, "is_claim": is_claim, "supported": human}


def _place(judge, human):
    return {"name": "p", "judge_in_destination": judge, "in_destination": human}


def test_agreement_over_accepted_claims_and_places():
    scores = [
        _score(claims=[_claim(True, True), _claim(False, True), _claim(False, None, is_claim=False)],
               places=[_place(True, True), _place(True, False)], missed=["opens at 4pm"]),
        _score("e002", claims=[_claim(False, False)], places=[_place(False, False)]),
    ]
    result = agreement(scores)

    assert result["faithfulness_agreement"] == pytest.approx(2 / 3)
    assert result["claims_compared"] == 3
    assert result["extraction_precision"] == pytest.approx(3 / 4)
    assert result["missed_claims"] == 1
    assert result["destination_agreement"] == pytest.approx(2 / 3)
    assert result["sample_size"] == 2
    assert result["sample_meets_minimum"] is False


def test_sample_of_twenty_meets_minimum():
    scores = [_score(f"e{i:03d}", claims=[_claim(True, True)]) for i in range(20)]
    assert agreement(scores)["sample_meets_minimum"] is True


def test_accepted_claim_needs_a_label():
    with pytest.raises(ValueError, match="no 'supported' label"):
        agreement([_score(claims=[_claim(True, None)])])


def test_empty_sample_gives_no_rates():
    result = agreement([])
    assert result["faithfulness_agreement"] is None
    assert result["destination_agreement"] is None


def test_load_scores_from_jsonl(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text(
        json.dumps({"entry_id": "e026", "claims": [_claim(True, True)], "places": [_place(True, True)]}) + "\n",
        encoding="utf-8",
    )
    assert load_scores(path)[0].entry_id == "e026"


def test_load_scores_reports_bad_line(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text('{"entry_id": "e1", "claims": [{"text": "x"}]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_scores(path)
