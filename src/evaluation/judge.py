"""LLM judge: faithfulness of specific claims, whether attractions are in the destination, and preference adherence.

The judge model is configured separately from the generation model
(``JUDGE_MODEL``, default ``gpt-6-luna``, called through the ``openai`` SDK with
structured outputs). Its prompts are versioned files in ``eval/judge_prompts/``
(``<name>_v<N>.md``); a change adds a new version instead of editing a file.

Public API::

    from evaluation.judge import Judge, faithfulness_summary, knowledge_context

    judge = Judge.from_env()
    verdict = judge.faithfulness(itinerary, knowledge_context(outcome.events))
    places = judge.destination(itinerary, destination="sydney", trip_length=3, notes=None)
    fit = judge.preference(itinerary, travel_style="family", notes=None)
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field

from evaluation.dataset import ROOT_DIR

PROMPTS_DIR = ROOT_DIR / "eval" / "judge_prompts"
DEFAULT_JUDGE_MODEL = "gpt-6-luna"
FAITHFULNESS_PROMPT = ("faithfulness", 2)
DESTINATION_PROMPT = ("destination", 2)
PREFERENCE_PROMPT = ("preference", 4)
NO_NOTES = "(none)"

# The last two exist from faithfulness v2 on; verdicts stored from v1 use the first four.
ClaimCategory = Literal["opening_hours", "price", "named_place", "transport", "activity", "season"]


class Claim(BaseModel):
    category: ClaimCategory
    text: str = Field(description="The claim, quoted from the itinerary")
    supported: bool


class FaithfulnessVerdict(BaseModel):
    claims: list[Claim]


class PlaceCheck(BaseModel):
    name: str
    in_destination: bool
    reason: str


class DestinationVerdict(BaseModel):
    places: list[PlaceCheck]

    @property
    def all_in_destination(self) -> bool:
        return all(place.in_destination for place in self.places)


class PreferenceCheck(BaseModel):
    preference: str = Field(description="What the traveller's words ask of the trip")
    followed: bool
    reason: str


class AddedRequirement(BaseModel):
    requirement: str
    quote: str = Field(description="The itinerary's words that impose or assume it")


class PreferenceVerdict(BaseModel):
    preferences: list[PreferenceCheck]
    added_requirements: list[AddedRequirement]


@dataclass(frozen=True)
class JudgeCall:
    """One judge call's parsed verdict and token usage."""

    verdict: BaseModel
    input_tokens: int
    output_tokens: int


def load_prompt(name: str, version: int, prompts_dir: Path = PROMPTS_DIR) -> str:
    return (prompts_dir / f"{name}_v{version}.md").read_text(encoding="utf-8")


def render(template: str, **values: str) -> str:
    """Substitute ``{key}`` placeholders; the prompts contain no other braces."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def knowledge_context(events: list[dict]) -> str:
    """The knowledge context the generator was given, rebuilt from the run's SSE events.

    Uses generate's own formatting, so the judge sees exactly the text the prompt had;
    empty when retrieval did not run.
    """
    from app.workflow.steps.generate import _extract_retrieved_context

    rag_event = next((e for e in events if e.get("step") == "rag_retrieve"), None)
    if rag_event is None:
        return ""
    step_input = StepInput(
        previous_step_outputs={"rag_retrieve": StepOutput(step_name="rag_retrieve", content=json.dumps(rag_event))}
    )
    return _extract_retrieved_context(step_input)


def itinerary_text(itinerary: dict) -> str:
    """The parts of an itinerary the judge reads: each day's activities and the tips."""
    lines = []
    for day in itinerary.get("daily_itinerary", []):
        lines.append(
            f"Day {day.get('day')}: morning: {day.get('morning')} | "
            f"afternoon: {day.get('afternoon')} | evening: {day.get('evening')}"
        )
    for tip in itinerary.get("key_tips", []):
        lines.append(f"Tip: {tip}")
    return "\n".join(lines)


class Judge:
    def __init__(self, client, model: str = DEFAULT_JUDGE_MODEL, prompts_dir: Path = PROMPTS_DIR):
        self._client = client
        self.model = model
        self.prompts_dir = prompts_dir

    @classmethod
    def from_env(cls) -> "Judge":
        from openai import OpenAI

        return cls(OpenAI(api_key=os.environ["OPENAI_API_KEY"]),
                   model=os.environ.get("JUDGE_MODEL", DEFAULT_JUDGE_MODEL))

    @property
    def prompt_versions(self) -> dict[str, int]:
        """Prompt name → version, for the run summary."""
        return dict([FAITHFULNESS_PROMPT, DESTINATION_PROMPT, PREFERENCE_PROMPT])

    def faithfulness(self, itinerary: dict, context: str) -> JudgeCall:
        prompt = render(
            load_prompt(*FAITHFULNESS_PROMPT, self.prompts_dir),
            knowledge_context=context or "(no knowledge context was given)",
            itinerary=itinerary_text(itinerary),
        )
        return self._ask(prompt, FaithfulnessVerdict)

    def destination(self, itinerary: dict, destination: str, trip_length: int, notes: str | None = None) -> JudgeCall:
        prompt = render(
            load_prompt(*DESTINATION_PROMPT, self.prompts_dir),
            destination=destination,
            trip_length=str(trip_length),
            notes=notes or NO_NOTES,
            itinerary=itinerary_text(itinerary),
        )
        return self._ask(prompt, DestinationVerdict)

    def preference(self, itinerary: dict, travel_style: str, notes: str | None = None) -> JudgeCall:
        prompt = render(
            load_prompt(*PREFERENCE_PROMPT, self.prompts_dir),
            travel_style=travel_style,
            notes=notes or NO_NOTES,
            itinerary=itinerary_text(itinerary),
        )
        return self._ask(prompt, PreferenceVerdict)

    def _ask(self, prompt: str, schema: type[BaseModel]) -> JudgeCall:
        response = self._client.responses.parse(model=self.model, input=prompt, text_format=schema)
        verdict = schema.model_validate(response.output_parsed)
        usage = response.usage
        return JudgeCall(verdict, usage.input_tokens, usage.output_tokens)


def faithfulness_summary(verdicts: list[tuple[FaithfulnessVerdict, bool]]) -> dict:
    """Share of supported claims, overall and split by whether the request had knowledge context.

    *verdicts* pairs each itinerary's verdict with whether its generator was given context.
    """
    return {
        "overall": _claim_share([verdict for verdict, _ in verdicts]),
        "with_context": _claim_share([verdict for verdict, had_context in verdicts if had_context]),
        "without_context": _claim_share([verdict for verdict, had_context in verdicts if not had_context]),
    }


def _claim_share(verdicts: list[FaithfulnessVerdict]) -> dict:
    claims = [claim for verdict in verdicts for claim in verdict.claims]
    supported = sum(claim.supported for claim in claims)
    return {
        "itineraries": len(verdicts),
        "claims": len(claims),
        "supported_share": supported / len(claims) if claims else None,
    }


def faithfulness_by_coverage(verdicts: list[tuple[FaithfulnessVerdict, str]]) -> dict:
    """The same share per ``corpus_coverage`` group, keyed by group name."""
    groups: dict[str, list[FaithfulnessVerdict]] = {}
    for verdict, coverage in verdicts:
        groups.setdefault(coverage, []).append(verdict)
    return {coverage: _claim_share(group) for coverage, group in sorted(groups.items())}


def preference_summary(verdicts: list[PreferenceVerdict]) -> dict:
    """Share of stated preferences the itineraries follow, and the requirements they add (counted, not scored)."""
    checks = [check for verdict in verdicts for check in verdict.preferences]
    return {
        "itineraries": len(verdicts),
        "preferences": len(checks),
        "followed_share": sum(check.followed for check in checks) / len(checks) if checks else None,
        "added_requirements": sum(len(verdict.added_requirements) for verdict in verdicts),
        "itineraries_with_added_requirements": sum(bool(verdict.added_requirements) for verdict in verdicts),
    }


def destination_rate(verdicts: list[DestinationVerdict]) -> float | None:
    """Share of itineraries whose every named place is in the destination."""
    return sum(v.all_in_destination for v in verdicts) / len(verdicts) if verdicts else None
