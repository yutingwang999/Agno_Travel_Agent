"""rebuild-rag tasks 2.2 to 2.4: judge prompt versions, preference adherence and re-judging. All text is made up.

The unit tests check what reaches the judge and how verdicts are counted. The tests marked
``integration`` call the real judge model, since only it can show that a prompt is understood.
"""

import json
import os
import random
from types import SimpleNamespace

import pytest

from evaluation.calibration import (
    agreement,
    destination_only_template,
    parse_review,
    render_review,
    stratified_template,
    unreviewed_items,
)
from evaluation.judge import (
    AddedRequirement,
    Claim,
    DestinationVerdict,
    FaithfulnessVerdict,
    Judge,
    PlaceCheck,
    PreferenceCheck,
    PreferenceVerdict,
    load_prompt,
    preference_summary,
)
from evaluation.rejudge import rejudge_record, rejudge_records, rejudged_metrics

ITINERARY = {
    "daily_itinerary": [{"day": 1, "morning": "Testville Zoo", "afternoon": "Harbour walk", "evening": "Dinner"}],
    "key_tips": ["Book ahead"],
}
TEXT = "Day 1: morning: Testville Zoo | afternoon: Harbour walk | evening: Dinner\nTip: Book ahead"


class FakeClient:
    """Stands in for openai.OpenAI; records prompts and answers by verdict type."""

    def __init__(self, fail_on=None):
        self.prompts = []
        self.fail_on = fail_on
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, model, input, text_format):
        self.prompts.append(input)
        if text_format is self.fail_on:
            raise ValueError("judge failed")
        verdict = {
            FaithfulnessVerdict: FaithfulnessVerdict(
                claims=[
                    Claim(category="activity", text="feed the giraffes at Testville Zoo", supported=False),
                    Claim(category="named_place", text="Testville Zoo", supported=True),
                ]
            ),
            DestinationVerdict: DestinationVerdict(places=[PlaceCheck(name="Testville Zoo", in_destination=True, reason="r")]),
            PreferenceVerdict: PreferenceVerdict(
                preferences=[PreferenceCheck(preference="animals", followed=True, reason="the zoo")],
                added_requirements=[AddedRequirement(requirement="step-free routes", quote="step-free")],
            ),
        }[text_format]
        return SimpleNamespace(output_parsed=verdict, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def _record(entry_id="e1", notes="kids love animals", **judge_fields):
    form = {"destination": "Testville", "trip_length": 2, "budget": "moderate", "travel_style": "family"}
    if notes:
        form["notes"] = notes
    return {
        "entry_id": entry_id,
        "form": form,
        "outcome": {"events": [{"step": "validate_output", "data": {"itinerary": ITINERARY}}]},
        "judge": {
            "faithfulness": {
                "itinerary_text": TEXT,
                "knowledge_context": "[Guide]\nMade up context.",
                "had_context": True,
                "verdict": {"claims": []},
                "input_tokens": 1,
                "output_tokens": 1,
                "version": 1,
            },
            "destination": {"verdict": {"places": []}, "input_tokens": 1, "output_tokens": 1, "version": 1},
            "error": None,
            **judge_fields,
        },
    }


# --- prompts --------------------------------------------------------------------------------------


def test_earlier_prompt_versions_stay_available():
    """Earlier results must stay reproducible."""
    assert "four categories" in load_prompt("faithfulness", 1)
    assert "{notes}" not in load_prompt("destination", 1)


def test_new_prompts_have_their_placeholders_and_kinds():
    faithfulness = load_prompt("faithfulness", 2)
    assert "`activity`" in faithfulness and "`season`" in faithfulness
    assert "{knowledge_context}" in faithfulness and "{itinerary}" in faithfulness
    assert "{notes}" in load_prompt("destination", 2)
    assert "{notes}" in load_prompt("preference", 1)
    assert "{notes}" in load_prompt("preference", 2)
    preference = load_prompt("preference", 3)
    assert "{travel_style}" in preference and "{notes}" in preference and "{itinerary}" in preference


def test_summary_records_the_versions_used():
    assert Judge(FakeClient()).prompt_versions == {"faithfulness": 2, "destination": 2, "preference": 3}


def test_destination_prompt_carries_the_notes():
    client = FakeClient()
    Judge(client).destination(ITINERARY, "testville", 2, notes="A stop at Faraway on the way.")
    assert "A stop at Faraway on the way." in client.prompts[0]


def test_preference_prompt_carries_style_notes_and_itinerary():
    client = FakeClient()
    call = Judge(client).preference(ITINERARY, "family", "kids love animals")

    assert "family" in client.prompts[0] and "kids love animals" in client.prompts[0] and "Testville Zoo" in client.prompts[0]
    assert call.verdict.preferences[0].followed is True


@pytest.mark.parametrize("call", ["destination", "preference"])
def test_absent_notes_are_stated_as_none(call):
    client = FakeClient()
    judge = Judge(client)
    if call == "destination":
        judge.destination(ITINERARY, "testville", 2)
    else:
        judge.preference(ITINERARY, "family")
    assert "(none)" in client.prompts[0] and "{notes}" not in client.prompts[0]


def test_stored_v1_verdicts_still_validate():
    verdict = FaithfulnessVerdict.model_validate({"claims": [{"category": "price", "text": "x", "supported": False}]})
    assert verdict.claims[0].category == "price"


# --- preference metric ----------------------------------------------------------------------------


def test_preference_summary_counts_followed_and_added():
    verdicts = [
        PreferenceVerdict(
            preferences=[
                PreferenceCheck(preference="followed", followed=True, reason="r"),
                PreferenceCheck(preference="ignored", followed=False, reason="r"),
            ],
            added_requirements=[AddedRequirement(requirement="step-free routes", quote="q")],
        ),
        PreferenceVerdict(preferences=[PreferenceCheck(preference="followed", followed=True, reason="r")], added_requirements=[]),
    ]

    assert preference_summary(verdicts) == {
        "itineraries": 2,
        "preferences": 3,
        "followed_share": 2 / 3,
        "added_requirements": 1,
        "itineraries_with_added_requirements": 1,
    }


def test_preference_summary_without_preferences_has_no_rate():
    assert preference_summary([])["followed_share"] is None


# --- re-judging -----------------------------------------------------------------------------------


def test_rejudging_keeps_the_stored_inputs_and_replaces_verdicts():
    client = FakeClient()
    record = rejudge_record(_record(), Judge(client, model="m"))

    judged = record["judge"]
    assert judged["faithfulness"]["version"] == 2
    assert judged["faithfulness"]["knowledge_context"] == "[Guide]\nMade up context."
    assert judged["faithfulness"]["verdict"]["claims"][0]["category"] == "activity"
    assert judged["destination"]["notes"] == "kids love animals"
    assert judged["preference"]["verdict"]["preferences"][0]["preference"] == "animals"
    assert "Made up context." in client.prompts[0]


def test_rejudging_can_keep_a_kind_as_stored():
    record = rejudge_record(_record(), Judge(FakeClient()), kinds=("preference",))

    assert record["judge"]["faithfulness"]["version"] == 1
    assert record["judge"]["destination"]["version"] == 1
    assert record["judge"]["preference"]["version"] == 3


def test_a_record_the_run_did_not_judge_stays_as_it_is():
    client = FakeClient()
    record = {"entry_id": "e1", "form": {}, "outcome": {"events": []}, "judge": {"faithfulness": None, "destination": None}}

    assert rejudge_record(record, Judge(client)) == record
    assert client.prompts == []


def test_a_stored_itinerary_that_differs_from_what_was_judged_is_an_error():
    record = _record()
    record["judge"]["faithfulness"]["itinerary_text"] = "Something else"

    with pytest.raises(ValueError, match="does not match"):
        rejudge_record(record, Judge(FakeClient()))


def test_a_judge_failure_is_recorded_and_left_out_of_the_numbers():
    pricing = SimpleNamespace(price=lambda model: SimpleNamespace(input=0.0, output=0.0))
    records = rejudge_records([_record("e1"), _record("e2")], Judge(FakeClient(fail_on=PreferenceVerdict)), concurrency=1)

    assert all(r["judge"]["rejudge_failed"] for r in records)
    assert "judge failed" in records[0]["judge"]["error"]
    assert rejudged_metrics(records, ("faithfulness",), "m", pricing)["rejudge"] == {"judged": 0, "judge_errors": 2, "cost_usd": 0.0}


def test_rejudged_metrics_come_from_the_new_verdicts():
    pricing = SimpleNamespace(price=lambda model: SimpleNamespace(input=1.0, output=1.0))
    records = rejudge_records([_record("e1"), _record("e2")], Judge(FakeClient()), concurrency=2)

    metrics = rejudged_metrics(records, ("faithfulness", "destination", "preference"), "m", pricing)

    assert metrics["faithfulness"]["with_context"]["claims"] == 4
    assert metrics["faithfulness"]["with_context"]["supported_share"] == 0.5
    assert metrics["destination"]["destination_rate"] == 1.0
    assert metrics["preference"]["followed_share"] == 1.0
    assert metrics["rejudge"]["judged"] == 2
    assert metrics["rejudge"]["cost_usd"] > 0


# --- calibration ----------------------------------------------------------------------------------


def _sampled():
    verdict = {
        "preferences": [{"preference": "animals", "followed": True, "reason": "the zoo"},
                        {"preference": "quiet", "followed": False, "reason": "busy"}],
        "added_requirements": [{"requirement": "step-free routes", "quote": "step-free"}],
    }
    score = stratified_template("e1", {"claims": []}, {"places": []}, random.Random(0), verdict)
    record = _record(preference={"verdict": verdict})
    return score, record


def test_every_preference_and_added_requirement_is_sampled():
    score, _ = _sampled()

    assert [p.preference for p in score.preferences] == ["animals", "quiet"]
    assert [a.requirement for a in score.added_requirements] == ["step-free routes"]
    assert len(unreviewed_items([score])) == 3


def test_a_run_without_the_preference_judge_samples_none():
    score = stratified_template("e1", {"claims": []}, {"places": []}, random.Random(0))

    assert score.preferences == [] and score.added_requirements == []


def test_preference_answers_round_trip_through_the_review_sheet():
    score, record = _sampled()

    sheet = render_review("run", [score], {"e1": record})
    assert "pr1  [followed: ?]" in sheet and "ar1  [added: ?]" in sheet and "the zoo" in sheet

    filled = (
        sheet.replace("pr1  [followed: ?]", "pr1  [followed: y]")
        .replace("pr2  [followed: ?]", "pr2  [followed: y]")
        .replace("ar1  [added: ?]", "ar1  [added: n]")
    )
    answered = parse_review(filled, [score])[0]

    assert [p.followed for p in answered.preferences] == [True, True]
    assert answered.added_requirements[0].added is False
    result = agreement([answered])["preference"]
    assert result["judge_followed"] == {"compared": 1, "agreement": 1.0}
    assert result["judge_not_followed"] == {"compared": 1, "agreement": 0.0}
    assert result["judge_added"] == {"compared": 1, "agreement": 0.0}


def test_less_common_preference_answers_are_reviewed_outside_the_sample():
    verdict = {
        "preferences": [{"preference": "animals", "followed": True, "reason": "r"},
                        {"preference": "quiet", "followed": False, "reason": "busy"}],
        "added_requirements": [{"requirement": "step-free routes", "quote": "step-free"}],
    }
    score = destination_only_template("e1", {"places": []}, verdict)

    assert score.destination_only and score.claims == [] and score.places == []
    assert [(p.preference, p.judge_followed) for p in score.preferences] == [("quiet", False)]
    assert [a.requirement for a in score.added_requirements] == ["step-free routes"]

    sheet = render_review("run", [score], {"e1": _record(preference={"verdict": verdict})})
    assert "pr1  [followed: ?]" in sheet and "ar1  [added: ?]" in sheet
    assert "**Places**" not in sheet and "**Claims**" not in sheet


# --- the real judge -------------------------------------------------------------------------------


@pytest.fixture
def judge():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    return Judge.from_env()


def _plan(morning: str, tip: str = "Bring water") -> dict:
    return {"daily_itinerary": [{"day": 1, "morning": morning, "afternoon": "Free time", "evening": "Dinner"}], "key_tips": [tip]}


def _claims(verdict, category):
    return [claim for claim in verdict.claims if claim.category == category]


@pytest.mark.integration
def test_activity_is_supported_at_the_right_place(judge):
    context = "[Guide]\nAt Marlow Bay visitors can swim with seals on guided boat tours."
    verdict = judge.faithfulness(_plan("Swim with seals at Marlow Bay"), context).verdict

    activities = _claims(verdict, "activity")
    assert activities and all(claim.supported for claim in activities), verdict


@pytest.mark.integration
def test_activity_is_unsupported_at_another_place(judge):
    context = "[Guide]\nAt Marlow Bay visitors can swim with seals. Dunmore Beach is a quiet stretch of sand."
    verdict = judge.faithfulness(_plan("Swim with seals at Dunmore Beach"), context).verdict

    activities = _claims(verdict, "activity")
    assert activities and not any(claim.supported for claim in activities), verdict


@pytest.mark.integration
def test_season_with_matching_months_is_supported(judge):
    context = "[Guide]\nThe best time for Marlow Bay's beaches is November to February."
    verdict = judge.faithfulness(_plan("Marlow Bay beach", "November to February is the best time for Marlow Bay's beaches"), context).verdict

    seasons = _claims(verdict, "season")
    assert seasons and all(claim.supported for claim in seasons), verdict


@pytest.mark.integration
def test_season_with_different_months_is_unsupported(judge):
    context = "[Guide]\nThe best time for Marlow Bay's beaches is November to February."
    verdict = judge.faithfulness(_plan("Marlow Bay beach", "June to August is the best time for Marlow Bay's beaches"), context).verdict

    seasons = _claims(verdict, "season")
    assert seasons and not any(claim.supported for claim in seasons), verdict


@pytest.mark.integration
def test_a_stop_asked_for_in_the_notes_is_in_scope(judge):
    plan = _plan("Drive to Kangaroo Island and spend the day at Seal Bay")
    with_notes = judge.destination(plan, "adelaide", 1, "Include Kangaroo Island.").verdict
    named = [place for place in with_notes.places if "Kangaroo Island" in place.name]

    assert named and all(place.in_destination for place in named), with_notes


@pytest.mark.integration
def test_a_far_place_nobody_asked_for_stays_out_of_scope(judge):
    plan = _plan("Fly to Uluru for a sunrise walk around the rock")
    verdict = judge.destination(plan, "adelaide", 1, "Include Kangaroo Island.").verdict

    assert not verdict.all_in_destination, verdict


@pytest.mark.integration
def test_a_followed_preference(judge):
    plan = {
        "daily_itinerary": [
            {"day": 1, "morning": "Street art lane tour", "afternoon": "Mural walk in the laneways", "evening": "Dinner"},
        ],
        "key_tips": ["Bring a camera"],
    }
    verdict = judge.preference(plan, "street art").verdict

    assert verdict.preferences and all(check.followed for check in verdict.preferences), verdict


@pytest.mark.integration
def test_an_ignored_preference(judge):
    plan = _plan("Shopping at the mall", "Wear comfortable shoes")
    verdict = judge.preference(plan, "surfing").verdict

    assert verdict.preferences and not any(check.followed for check in verdict.preferences), verdict


@pytest.mark.integration
def test_an_added_requirement(judge):
    plan = _plan("Harbour walk on a step-free, wheelchair-accessible route", "All venues chosen have lifts and step-free access for wheelchair users")
    verdict = judge.preference(plan, "seniors, slow pace").verdict

    assert verdict.added_requirements, verdict
    assert json.dumps(verdict.model_dump())


@pytest.mark.integration
def test_a_planned_meal_is_not_an_added_requirement(judge):
    plan = _plan("Fish and chips by the harbour, then a vegetarian dinner at a garden cafe", "Eat seafood at the pier")
    verdict = judge.preference(plan, "beaches").verdict

    assert not verdict.added_requirements, verdict


@pytest.mark.integration
def test_etiquette_and_what_the_traveller_stated_are_not_added_requirements(judge):
    plan = _plan("Family morning at the zoo with the children", "Follow the rules at sacred sites and wear a hat")
    verdict = judge.preference(plan, "family").verdict

    assert not verdict.added_requirements, verdict


@pytest.mark.integration
def test_an_assumed_diet_is_an_added_requirement(judge):
    plan = _plan("Lunch at a vegan cafe", "Every meal here is vegan because you do not eat animal products")
    verdict = judge.preference(plan, "food").verdict

    assert verdict.added_requirements, verdict


@pytest.mark.integration
def test_a_demanding_activity_assumes_nothing_about_ability(judge):
    plan = _plan("Morning ascent of Mount Marlow on a guided hike, then a beginner surf lesson", "Bring water")
    verdict = judge.preference(plan, "art and fine dining").verdict

    assert not verdict.added_requirements, verdict


@pytest.mark.integration
def test_a_restriction_on_movement_is_still_an_added_requirement(judge):
    plan = _plan("Harbour walk on a step-free route", "Every venue here avoids stairs because you cannot manage steps")
    verdict = judge.preference(plan, "art").verdict

    assert verdict.added_requirements, verdict
