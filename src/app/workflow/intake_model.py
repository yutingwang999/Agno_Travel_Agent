"""Pydantic input model for Step 1: intake.

Defines the validated and normalised data contract for the travel planning
workflow.  All downstream steps read their input from the normalised fields
that this model produces.

Fields (all required):
    destination   — free-text location, normalised to lowercase + stripped
    trip_length   — number of days (must be >= 1)
    budget        — budget descriptor (e.g. "budget", "moderate", "luxury")
    travel_style  — style descriptor (e.g. "family", "adventure", "romantic")

Validation errors raise ``pydantic.ValidationError``, which FastAPI maps to a
422 Unprocessable Entity response.  The intake step must not swallow this
exception — callers are expected to handle or propagate it.
"""

from pydantic import BaseModel, ConfigDict, field_validator


class TravelRequest(BaseModel):
    """Validated and normalised travel planning request."""

    model_config = ConfigDict(extra="ignore")

    destination: str
    trip_length: int
    budget: str
    travel_style: str

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
        """Trip length must be at least 1 day."""
        if value < 1:
            raise ValueError("trip_length must be at least 1")
        return value

    @field_validator("budget")
    @classmethod
    def validate_budget(cls, value: str) -> str:
        """Budget must be a non-empty string."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("budget must not be empty")
        return stripped

    @field_validator("travel_style")
    @classmethod
    def validate_travel_style(cls, value: str) -> str:
        """Travel style must be a non-empty string."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("travel_style must not be empty")
        return stripped
