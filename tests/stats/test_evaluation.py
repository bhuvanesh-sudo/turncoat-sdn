"""Tests for combined evaluation reports."""

import json

import pytest

from turncoat_sdn.stats.evaluation import build_evaluation_report


@pytest.fixture
def rows():
    result = []
    values = {
        "random": [0.4, 0.3, 0.5, 0.35],
        "round_robin": [0.3, 0.2, 0.4, 0.25],
    }
    for strategy, observations in values.items():
        for seed, value in enumerate(observations, start=1):
            result.append(
                {
                    "strategy": strategy,
                    "scenario": "sybil",
                    "seed": seed,
                    "slo_violation_rate": value,
                }
            )
    return result


def evaluate(rows):
    return build_evaluation_report(
        rows,
        strategies=("random", "round_robin"),
        scenarios=("sybil",),
        metrics=("slo_violation_rate",),
        resamples=200,
        bootstrap_seed=42,
    )


def test_report_has_summaries_and_comparisons(rows):
    report = evaluate(rows)
    assert report["schema_version"] == 1
    assert len(report["summaries"]) == 2
    assert report["n_comparisons"] == 1
    assert report["configuration"]["correction"] == "Holm"
    metric = report["summaries"][0]["slo_violation_rate"]
    assert metric["count"] == 4
    assert metric["ci_low"] <= metric["mean"] <= metric["ci_high"]


def test_report_is_json_serializable(rows):
    assert json.loads(json.dumps(evaluate(rows), allow_nan=False))["schema_version"] == 1


def test_results_are_reproducible(rows):
    assert evaluate(rows) == evaluate(rows)


def test_null_metric_is_not_counted_as_zero(rows):
    rows[0]["slo_violation_rate"] = None
    report = evaluate(rows)
    summary = next(item for item in report["summaries"] if item["strategy"] == "random")
    assert summary["slo_violation_rate"]["count"] == 3


def test_unknown_metric_is_rejected(rows):
    with pytest.raises(ValueError, match="unknown metrics"):
        build_evaluation_report(
            rows,
            strategies=("random", "round_robin"),
            scenarios=("sybil",),
            metrics=("not_a_metric",),
        )


def test_mismatched_seeds_are_rejected(rows):
    rows.pop()
    with pytest.raises(ValueError):
        evaluate(rows)
