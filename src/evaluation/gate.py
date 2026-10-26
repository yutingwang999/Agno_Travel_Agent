"""Regression gate: check a run summary against ``eval/thresholds.yaml``.

Each gated metric names a dotted path into ``summary.json`` and a ``min`` (fail
when below) or a ``max`` (fail when above). A metric without a value in the run
fails too, so a broken run cannot pass.

Public API::

    from evaluation.gate import check, load_thresholds

    failures = check(summary, load_thresholds())   # [] means the gate passes
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from evaluation.compare import get
from evaluation.dataset import ROOT_DIR

THRESHOLDS_PATH = ROOT_DIR / "eval" / "thresholds.yaml"


class ThresholdsNotSet(Exception):
    """Raised when a gated metric has neither a min nor a max value yet."""


class Bound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _one_direction(self) -> "Bound":
        if self.min is not None and self.max is not None:
            raise ValueError("a gated metric takes either min or max, not both")
        return self


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: str
    subset: str
    metrics: dict[str, Bound]


def load_thresholds(path: Path = THRESHOLDS_PATH) -> Thresholds:
    return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def check(summary: dict, thresholds: Thresholds) -> list[str]:
    """Return one message per failing metric; an empty list means the gate passes."""
    unset = [name for name, bound in thresholds.metrics.items() if bound.min is None and bound.max is None]
    if unset:
        raise ThresholdsNotSet(f"no threshold value for: {', '.join(unset)} (set them in task 6.3)")

    failures = []
    for name, bound in thresholds.metrics.items():
        value = get(summary, bound.path)
        if not isinstance(value, (int, float)):
            failures.append(f"{name}: no value in the run ({bound.path})")
        elif bound.min is not None and value < bound.min:
            failures.append(f"{name}: {value:.3f} is below the minimum {bound.min:.3f}")
        elif bound.max is not None and value > bound.max:
            failures.append(f"{name}: {value:.3f} is above the maximum {bound.max:.3f}")
    return failures
