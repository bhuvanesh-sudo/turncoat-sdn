"""Tests for v0.3 descriptive benchmark statistics."""

import pytest

from turncoat_sdn.stats.descriptive import summarize, summarize_metrics


def test_summarize_multiple_values() -> None:
    result = summarize([1, 2, 3])

    assert result.count == 3
    assert result.mean == 2
    assert result.sample_stddev == pytest.approx(1)
    assert result.minimum == 1
    assert result.maximum == 3


def test_summarize_empty_values() -> None:
    result = summarize([])

    assert result.count == 0
    assert result.mean is None
    assert result.sample_stddev is None
    assert result.minimum is None
    assert result.maximum is None


def test_summarize_single_value_has_no_sample_stddev() -> None:
    result = summarize([4])

    assert result.count == 1
    assert result.mean == 4
    assert result.sample_stddev is None
    assert result.minimum == 4
    assert result.maximum == 4


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_summarize_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        summarize([value])


@pytest.mark.parametrize("value", [True, "2", None])
def test_summarize_rejects_non_numeric_values(value: object) -> None:
    with pytest.raises(TypeError, match="numeric"):
        summarize([value])  # type: ignore[list-item]


def test_summarize_metrics_groups_runs() -> None:
    records = [
        {"strategy": "random", "scenario": "sybil", "detection_rate": 0.5},
        {"strategy": "random", "scenario": "sybil", "detection_rate": 1.0},
        {"strategy": "zt_sdn", "scenario": "sybil", "detection_rate": 0.75},
    ]

    result = summarize_metrics(records)

    random_result = next(row for row in result if row["strategy"] == "random")
    assert random_result["runs"] == 2
    assert random_result["detection_rate"]["count"] == 2
    assert random_result["detection_rate"]["mean"] == pytest.approx(0.75)
    assert random_result["detection_rate"]["minimum"] == 0.5
    assert random_result["detection_rate"]["maximum"] == 1.0
    assert random_result["false_positive_rate"]["count"] == 0


def test_summarize_metrics_skips_missing_metric_values() -> None:
    result = summarize_metrics(
        [
            {"strategy": "random", "scenario": "clean", "detection_rate": 0.5},
            {"strategy": "random", "scenario": "clean", "detection_rate": None},
        ]
    )

    assert result[0]["runs"] == 2
    assert result[0]["detection_rate"]["count"] == 1
    assert result[0]["detection_rate"]["mean"] == 0.5


def test_summarize_metrics_rejects_missing_group_key() -> None:
    with pytest.raises(ValueError, match="grouping keys"):
        summarize_metrics([{"strategy": "random"}])


def test_summarize_metrics_rejects_invalid_metric() -> None:
    with pytest.raises(TypeError, match="numeric"):
        summarize_metrics([{"strategy": "random", "scenario": "clean", "detection_rate": "high"}])
