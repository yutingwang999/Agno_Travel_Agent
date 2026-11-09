"""LLM judge: faithfulness of specific claims, whether attractions are in the destination, preference adherence,
and whether each cited knowledge chunk supports the day that cites it.

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
    cites = judge.citation(itinerary, cited_blocks(outcome.events, itinerary))
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
CITATION_PROMPT = ("citation", 1)
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


class CitationCheck(BaseModel):
    day: int
    id: str = Field(description="The cited block id, such as S2")
    supported: bool
    item: str = Field(description="What the day plans that the block states; empty when not supported")
    reason: str


class CitationVerdict(BaseModel):
    checks: list[CitationCheck]


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

    step_input = _rag_step_input(events)
    return _extract_retrieved_context(step_input)[0] if step_input else ""


def _rag_step_input(events: list[dict]) -> StepInput | None:
    rag_event = next((e for e in events if e.get("step") == "rag_retrieve"), None)
    if rag_event is None:
        return None
    return StepInput(
        previous_step_outputs={"rag_retrieve": StepOutput(step_name="rag_retrieve", content=json.dumps(rag_event))}
    )


def cited_blocks(events: list[dict], itinerary: dict) -> dict[str, str]:
    """The knowledge chunks the itinerary cites, by citation id: ``{"S2": "<title>\\n<text>"}``.

    Numbered exactly as generate numbered them for the prompt; ids a day cites that
    were not in the context are left out (the citation rule rejects those anyway).
    """
    from app.workflow.steps.generate import _retrieved_chunks, citation_id

    step_input = _rag_step_input(events)
    if step_input is None:
        return {}
    blocks = {citation_id(n): f"{c.get('title') or ''}\n{c.get('chunk_text') or ''}"
              for n, c in enumerate(_retrieved_chunks(step_input), start=1)}
    cited = {cid for day in itinerary.get("daily_itinerary", []) for cid in day.get("sources") or []}
    return {cid: text for cid, text in blocks.items() if cid in cited}


def citation_pairs(itinerary: dict, block_ids) -> list[tuple[int, str]]:
    """Every (day, cited id) pair to judge, in itinerary order, once each."""
    pairs = []
    for day in itinerary.get("daily_itinerary", []):
        for cid in day.get("sources") or []:
            if cid in block_ids and (day.get("day"), cid) not in pairs:
                pairs.append((day.get("day"), cid))
    return pairs


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
        return dict([FAITHFULNESS_PROMPT, DESTINATION_PROMPT, PREFERENCE_PROMPT, CITATION_PROMPT])

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

    def citation(self, itinerary: dict, blocks: dict[str, str]) -> JudgeCall:
        """Judge every (day, cited block) pair; no call, and no checks, when nothing is cited.

        Checks the judge returns for pairs that were not asked are dropped, and a pair
        it answers twice keeps the first answer, so the verdict holds at most one check
        per pair in itinerary order; a pair it skips is missing from the verdict.
        """
        pairs = citation_pairs(itinerary, blocks)
        if not pairs:
            return JudgeCall(CitationVerdict(checks=[]), 0, 0)
        days = {day.get("day"): day for day in itinerary.get("daily_itinerary", [])}
        cited_ids = sorted({cid for _, cid in pairs}, key=lambda cid: list(blocks).index(cid))
        day_lines = []
        for number in dict.fromkeys(day for day, _ in pairs):
            day = days[number]
            ids = ", ".join(cid for d, cid in pairs if d == number)
            day_lines.append(f"Day {number} (cites {ids}): morning: {day.get('morning')} | "
                             f"afternoon: {day.get('afternoon')} | evening: {day.get('evening')}")
        prompt = render(
            load_prompt(*CITATION_PROMPT, self.prompts_dir),
            blocks="\n\n".join(f"[{cid}] {blocks[cid]}" for cid in cited_ids),
            days="\n".join(day_lines),
        )
        call = self._ask(prompt, CitationVerdict)
        by_pair: dict[tuple[int, str], CitationCheck] = {}
        for check in call.verdict.checks:
            by_pair.setdefault((check.day, check.id), check)
        verdict = CitationVerdict(checks=[by_pair[p] for p in pairs if p in by_pair])
        return JudgeCall(verdict, call.input_tokens, call.output_tokens)

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


def citation_summary(items: list[tuple[CitationVerdict, dict, dict[str, str], bool]]) -> dict:
    """Citation accuracy (spec "Citation accuracy metric").

    *items* holds, per judged itinerary, its citation verdict, the itinerary, the blocks
    it cites and whether its generator was given knowledge context. Reports the share
    of judged (day, block) citations that the block supports, and, over the days of
    itineraries that had context, the share that cite at least one block.
    """
    checks = [check for verdict, _, _, _ in items for check in verdict.checks]
    expected = sum(len(citation_pairs(itinerary, blocks)) for _, itinerary, blocks, _ in items)
    days = [day for _, itinerary, _, had_context in items if had_context
            for day in itinerary.get("daily_itinerary", [])]
    return {
        "itineraries": len(items),
        "itineraries_citing": sum(bool(verdict.checks) for verdict, _, _, _ in items),
        "citations": len(checks),
        "supported_share": sum(check.supported for check in checks) / len(checks) if checks else None,
        "missing_checks": expected - len(checks),
        "days_with_context": len(days),
        "days_citing_share": sum(bool(day.get("sources")) for day in days) / len(days) if days else None,
    }


def citation_by_coverage(items: list[tuple[CitationVerdict, dict, dict[str, str], bool, str]]) -> dict:
    """:func:`citation_summary` per ``corpus_coverage`` group, keyed by group name."""
    groups: dict[str, list] = {}
    for *item, coverage in items:
        groups.setdefault(coverage, []).append(tuple(item))
    return {coverage: citation_summary(group) for coverage, group in sorted(groups.items())}


def destination_rate(verdicts: list[DestinationVerdict]) -> float | None:
    """Share of itineraries whose every named place is in the destination."""
    return sum(v.all_in_destination for v in verdicts) / len(verdicts) if verdicts else None
