"""Schemas of request parsing (parse-requests).

- ``ParseInput``: the body of ``POST /parse``.
- ``ParserOutput``: the parser model's structured output (also its response
  schema). It is deliberately loose: an out-of-range trip length or a missing
  field must reach the code, which leaves the field empty and lists it in
  ``missing`` (design decisions 2 and 3).
- ``ParsedRequest``: the ``request`` of the response, the form's fields after
  the defaults. ``destination`` and ``trip_length`` may be empty for the user to
  fill in; ``budget`` and ``travel_style`` always have a value.
- ``Assumption`` and ``ParseResponse``: the rest of the response.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.workflow.config import MAX_PARSE_TEXT_LENGTH
from app.workflow.intake_model import BudgetLevel

# Fields /parse leaves empty for the user when the sentence does not give them.
RequiredField = Literal["destination", "trip_length"]
# Fields /parse fills with a default, each listed as an assumption.
DefaultedField = Literal["budget", "travel_style"]


class ParseInput(BaseModel):
    """Body of ``POST /parse``: one free-text request."""

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Strip whitespace; blank or too long text is a validation error (422)."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be empty")
        if len(stripped) > MAX_PARSE_TEXT_LENGTH:
            raise ValueError(f"text must be at most {MAX_PARSE_TEXT_LENGTH} characters")
        return stripped


class ParserOutput(BaseModel):
    """What the parser model reads from the sentence; unstated fields are null."""

    is_travel_request: bool
    destination: str | None = None
    trip_length: int | None = None
    budget: BudgetLevel | None = None
    max_daily_budget_aud: int | None = None
    travel_style: str | None = None
    notes: str | None = None
    preferences: list[str] = Field(default_factory=list)


class ParsedRequest(BaseModel):
    """The form's fields as parsed, after the defaults."""

    destination: str | None = None
    trip_length: int | None = None
    budget: BudgetLevel
    travel_style: str
    max_daily_budget_aud: int | None = None
    notes: str | None = None


class Assumption(BaseModel):
    """A default /parse applied because the sentence did not state the field."""

    field: DefaultedField
    value: str
    message: str


class ParseResponse(BaseModel):
    """Successful ``POST /parse`` response."""

    parse_id: str
    request: ParsedRequest
    preferences: list[str]
    assumptions: list[Assumption]
    missing: list[RequiredField]
