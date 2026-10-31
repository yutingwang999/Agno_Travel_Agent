"""Input guards run before the workflow (harden-workflow-guardrails, design decision 6).

Two checks, in this order, on a request that passed field validation:

1. prompt injection — every free-text field against ``PROMPT_INJECTION_PATTERNS``
   → ``input_rejected``
2. destination      — must be in the Australian place list; a match is replaced
   by its canonical English name → ``destination_out_of_scope``

A rejection raises :class:`GuardRejection`; ``main.py`` turns it into a 422 with
``{"reason": <code>, "detail": <fixed message>}``.  The message is fixed per code
and never echoes the input or names the pattern or field that matched: telling a
caller which rule fired would show how to get around it.  Neither check calls an
external API.

Public API:
    GuardRejection
    REJECTION_MESSAGES
    guard_request(request) -> TravelRequest
"""

import re

from app.workflow.config import PROMPT_INJECTION_PATTERNS
from app.workflow.intake_model import TravelRequest
from app.workflow.places import canonical_destination

DESTINATION_OUT_OF_SCOPE = "destination_out_of_scope"
INPUT_REJECTED = "input_rejected"

REJECTION_MESSAGES: dict[str, str] = {
    DESTINATION_OUT_OF_SCOPE: "Please enter one specific destination in Australia, such as Sydney, Cairns or Tasmania.",
    INPUT_REJECTED: "Your request could not be processed. Please rephrase it and try again.",
}

# The request fields users type freely; the others are enums and integers.
FREE_TEXT_FIELDS = ("destination", "travel_style")

_INJECTION = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in PROMPT_INJECTION_PATTERNS]


class GuardRejection(Exception):
    """A request refused by an input guard; carries the reason code only."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.detail = REJECTION_MESSAGES[reason]


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION)


def guard_request(request: TravelRequest) -> TravelRequest:
    """Return *request* with its canonical destination, or raise GuardRejection."""
    for field in FREE_TEXT_FIELDS:
        if looks_like_injection(str(getattr(request, field))):
            raise GuardRejection(INPUT_REJECTED)
    canonical = canonical_destination(request.destination)
    if canonical is None:
        raise GuardRejection(DESTINATION_OUT_OF_SCOPE)
    return request.model_copy(update={"destination": canonical})
