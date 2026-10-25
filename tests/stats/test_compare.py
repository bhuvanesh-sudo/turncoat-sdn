"""Tests for multi-strategy paired comparison reports."""

import pytest

from turncoat_sdn.stats.compare import (
    AdjustedComparison,
    ComparisonReport,
    compare_strategies,
)


@pytest.fixture
def rows():
    records = []
    values = {
        "random": [0.40, 0.35, 0.45, 0.30],
        "round_robin": [0.30, 0.25, 0.35, 0.20],
        "zero_trust": [0.10, 0.12, 0.15, 0.08],
    }
    for strategy, observations in values.items():
        for seed, value in enumerate(observations, start=1):
            records.append(
                {
                    "strategy": strategy,
                    "scenario": "sybil",
                    "seed": seed,
                    "slo_violation_rate": value,
                    "mean_latency_ms": value * 100,
                }
            )
    return records


def test_report_compares_each_strategy_pair(rows):
    report = compare_strategies(
        rows,
        strategies=["random", "round_robin", "zero_trust"],
        scenarios=["sybil"],
        metrics=["slo_violation_rate"],
    )
    assert isinstance(report, ComparisonReport)
    assert report.n_comparisons == 3
    assert {
        (
            item.comparison.strategy_a,
            item.comparison.strategy_b,
        )
        for item in report.comparisons
    } == {
        ("random", "round_robin"),
        ("random", "zero_trust"),
        ("round_robin", "zero_trust"),
    }


def test_all_comparisons_receive_adjusted_p_values(rows):
    report = compare_strategies(
        rows,
        strategies=["random", "zero_trust"],
        scenarios=["sybil"],
        metrics=["slo_violation_rate", "mean_latency_ms"],
    )
    assert report.n_comparisons == 2
    for item in report.comparisons:
        assert isinstance(item, AdjustedComparison)
        assert item.comparison.p_value <= item.adjusted_p_value <= 1.0


def test_report_counts_significant_results(rows):
    report = compare_strategies(
        rows,
        strategies=["random", "zero_trust"],
        scenarios=["sybil"],
        metrics=["slo_violation_rate"],
        alpha=0.05,
    )
    assert report.n_significant == sum(item.significant for item in report.comparisons)


@pytest.mark.parametrize("alpha", [0, 1, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_alpha_is_rejected(rows, alpha):
    with pytest.raises(ValueError):
        compare_strategies(
            rows,
            strategies=["random", "zero_trust"],
            scenarios=["sybil"],
            metrics=["slo_violation_rate"],
            alpha=alpha,
        )


@pytest.mark.parametrize(
    ("strategies", "scenarios", "metrics"),
    [
        ([], ["sybil"], ["slo_violation_rate"]),
        (["random"], ["sybil"], ["slo_violation_rate"]),
        (["random", "random"], ["sybil"], ["slo_violation_rate"]),
        (["random", "zero_trust"], [], ["slo_violation_rate"]),
        (["random", "zero_trust"], ["sybil"], []),
    ],
)
def test_invalid_selection_is_rejected(rows, strategies, scenarios, metrics):
    with pytest.raises(ValueError):
        compare_strategies(
            rows,
            strategies=strategies,
            scenarios=scenarios,
            metrics=metrics,
        )


def test_missing_requested_strategy_fails(rows):
    with pytest.raises(ValueError, match="no rows found"):
        compare_strategies(
            rows,
            strategies=["random", "missing"],
            scenarios=["sybil"],
            metrics=["slo_violation_rate"],
        )


def test_missing_requested_scenario_fails(rows):
    with pytest.raises(ValueError, match="no rows found"):
        compare_strategies(
            rows,
            strategies=["random", "zero_trust"],
            scenarios=["unknown"],
            metrics=["slo_violation_rate"],
        )


def test_comparison_order_is_deterministic(rows):
    report = compare_strategies(
        rows,
        strategies=["random", "round_robin", "zero_trust"],
        scenarios=["sybil"],
        metrics=["slo_violation_rate", "mean_latency_ms"],
    )
    observed = [
        (
            item.comparison.scenario,
            item.comparison.metric,
            item.comparison.strategy_a,
            item.comparison.strategy_b,
        )
        for item in report.comparisons
    ]
    assert observed == [
        ("sybil", "slo_violation_rate", "random", "round_robin"),
        ("sybil", "slo_violation_rate", "random", "zero_trust"),
        ("sybil", "slo_violation_rate", "round_robin", "zero_trust"),
        ("sybil", "mean_latency_ms", "random", "round_robin"),
        ("sybil", "mean_latency_ms", "random", "zero_trust"),
        ("sybil", "mean_latency_ms", "round_robin", "zero_trust"),
    ]


class TestCompareStrategiesEdgeCases:
    def test_string_instead_of_strategy_sequence_is_rejected(self, rows):
        with pytest.raises(TypeError, match="sequence of strings"):
            compare_strategies(
                rows,
                strategies="random",
                scenarios=["sybil"],
                metrics=["slo_violation_rate"],
            )

    def test_non_string_selection_is_rejected(self, rows):
        with pytest.raises(ValueError, match="non-empty strings"):
            compare_strategies(
                rows,
                strategies=["random", 42],
                scenarios=["sybil"],
                metrics=["slo_violation_rate"],
            )

    def test_boolean_alpha_is_rejected(self, rows):
        with pytest.raises(TypeError, match="alpha"):
            compare_strategies(
                rows,
                strategies=["random", "zero_trust"],
                scenarios=["sybil"],
                metrics=["slo_violation_rate"],
                alpha=True,
            )

    def test_missing_required_row_key_is_rejected(self):
        malformed = {"strategy": "random", "scenario": "sybil"}
        valid = {
            "strategy": "zero_trust",
            "scenario": "sybil",
            "seed": 1,
            "slo_violation_rate": 0.1,
        }
        with pytest.raises(ValueError, match="required keys"):
            compare_strategies(
                [malformed, valid],
                strategies=["random", "zero_trust"],
                scenarios=["sybil"],
                metrics=["slo_violation_rate"],
            )
