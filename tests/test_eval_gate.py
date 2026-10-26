"""build-evaluation-harness: regression gate thresholds (min and max)."""

import pytest

from evaluation.gate import Thresholds, ThresholdsNotSet, check, load_thresholds

SUMMARY = {"metrics": {"system": {"format_pass_rate": 0.9, "error_rate": 0.1},
                       "retrieval": {"recall_at_k": None}}}


def _thresholds(**metrics) -> Thresholds:
    return Thresholds.model_validate({"config": "v010-baseline", "subset": "smoke", "metrics": metrics})


def test_metric_below_minimum_fails_and_is_named():
    """Spec scenario: format pass rate below its minimum."""
    failures = check(SUMMARY, _thresholds(format_pass_rate={"path": "metrics.system.format_pass_rate", "min": 1.0}))
    assert failures == ["format_pass_rate: 0.900 is below the minimum 1.000"]


def test_metric_above_maximum_fails_and_is_named():
    """Spec scenario: error rate above its maximum."""
    failures = check(SUMMARY, _thresholds(error_rate={"path": "metrics.system.error_rate", "max": -1}))
    assert failures == ["error_rate: 0.100 is above the maximum -1.000"]


def test_within_bounds_passes():
    thresholds = _thresholds(
        format_pass_rate={"path": "metrics.system.format_pass_rate", "min": 0.8},
        error_rate={"path": "metrics.system.error_rate", "max": 0.2},
    )
    assert check(SUMMARY, thresholds) == []


def test_missing_value_fails():
    failures = check(SUMMARY, _thresholds(recall={"path": "metrics.retrieval.recall_at_k", "min": 0.5}))
    assert failures == ["recall: no value in the run (metrics.retrieval.recall_at_k)"]


def test_unset_threshold_is_an_error_not_a_pass():
    with pytest.raises(ThresholdsNotSet, match="error_rate"):
        check(SUMMARY, _thresholds(error_rate={"path": "metrics.system.error_rate", "max": None}))


def test_min_and_max_together_are_rejected():
    with pytest.raises(ValueError, match="either min or max"):
        _thresholds(x={"path": "a", "min": 0.1, "max": 0.9})


def test_repository_threshold_file_lists_the_gated_metrics():
    thresholds = load_thresholds()
    assert thresholds.subset == "smoke"
    assert set(thresholds.metrics) == {"format_pass_rate", "trip_length_rate", "budget_rate",
                                       "recall_at_5", "error_rate"}
    assert thresholds.metrics["error_rate"].min is None  # a maximum, not a minimum
