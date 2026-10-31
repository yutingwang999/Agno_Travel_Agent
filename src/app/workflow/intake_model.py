"""Pydantic input model for Step 1: intake.

Defines the validated and normalised data contract for the travel planning
workflow.  All downstream steps read their input from the normalised fields
that this model produces.

Fields:
    destination          — free-text location, normalised to lowercase + stripped
    trip_length          — number of days, 1 to MAX_TRIP_LENGTH_DAYS (14)
    budget               — enumerated budget level: "budget", "moderate", or "luxury"
    travel_style         — free-text style descriptor (e.g. "family", "adventure");
                           kept as free text so the CAG step can perform semantic
                           matching against it
    max_daily_budget_aud — optional whole AUD per person per day, excluding
                           accommodation (>= 1, no upper bound); when given it
                           sets the request's daily budget ceiling instead of the
                           level's default (see app.workflow.budget)

Validation errors raise ``pydantic.ValidationError``, which FastAPI maps to a
422 Unprocessable Entity response.  The intake step must not swallow this
exception — callers are expected to handle or propagate it.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.workflow.config import MAX_TRIP_LENGTH_DAYS


class BudgetLevel(StrEnum):
    """Enumerated budget levels accepted by the travel planning form.

    Using StrEnum means each member is also a plain ``str``, so it serialises
    to JSON, formats into prompt templates, and compares with string literals
    without any conversion.
    """

    budget = "budget"
    moderate = "moderate"
    luxury = "luxury"


class TravelRequest(BaseModel):
    """Validated and normalised travel planning request."""

    model_config = ConfigDict(extra="ignore")

    destination: str
    trip_length: int
    budget: BudgetLevel
    travel_style: str
    # A fractional amount is rejected (422), like a fractional trip_length.
    max_daily_budget_aud: int | None = Field(default=None, ge=1)

    @field_validator("destination")
    @classmethod
    def normalise_destination(cls, value: str) -> str:
        """Strip whitespace and convert to lowercase."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("destination must not be empty")
        return stripped.lower()

    @field_validator("trip_length")
    @classmethod
    def validate_trip_length(cls, value: int) -> int:
        """Trip length must be between 1 and MAX_TRIP_LENGTH_DAYS days."""
        if value < 1:
            raise ValueError("trip_length must be at least 1")
        if value > MAX_TRIP_LENGTH_DAYS:
            raise ValueError(f"trip_length must be at most {MAX_TRIP_LENGTH_DAYS}")
        return value

    @field_validator("travel_style")
    @classmethod
    def validate_travel_style(cls, value: str) -> str:
        """Travel style must be a non-empty string."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("travel_style must not be empty")
        return stripped
