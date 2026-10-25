import pytest

from turncoat_sdn.stats.robustness import rank_strategies


def test_rank_strategies_respects_metric_direction_across_scenarios():
    rows = [
        {"strategy": "A", "scenario": "one", "seed": 1, "failure_rate": 0.1},
        {"strategy": "A", "scenario": "one", "seed": 2, "failure_rate": 0.3},
        {"strategy": "B", "scenario": "one", "seed": 1, "failure_rate": 0.2},
        {"strategy": "A", "scenario": "two", "seed": 1, "failure_rate": 0.1},
        {"strategy": "B", "scenario": "two", "seed": 1, "failure_rate": 0.3},
    ]

    report = rank_strategies(rows, metric="failure_rate")

    assert report["overall_rankings"][0]["strategy"] == "A"
    assert report["overall_rankings"][0]["average_rank"] == pytest.approx(1.25)
    assert report["overall_rankings"][1]["average_rank"] == pytest.approx(1.75)


def test_rank_strategies_handles_higher_is_better_metrics():
    rows = [
        {"strategy": "A", "scenario": "one", "detection_rate": 0.8},
        {"strategy": "B", "scenario": "one", "detection_rate": 0.9},
    ]

    report = rank_strategies(rows, metric="detection_rate")

    assert report["higher_is_better"] is True
    assert report["overall_rankings"][0]["strategy"] == "B"


def test_rank_strategies_averages_tied_ranks():
    rows = [
        {"strategy": "A", "scenario": "one", "failure_rate": 0.1},
        {"strategy": "B", "scenario": "one", "failure_rate": 0.1},
        {"strategy": "C", "scenario": "one", "failure_rate": 0.3},
    ]

    report = rank_strategies(rows, metric="failure_rate")
    ranks = report["scenario_rankings"][0]["ranks"]

    assert ranks["A"] == 1.5
    assert ranks["B"] == 1.5
    assert ranks["C"] == 3.0


def test_rank_strategies_ignores_missing_values_when_averaging_seeds():
    rows = [
        {"strategy": "A", "scenario": "one", "failure_rate": 0.1},
        {"strategy": "A", "scenario": "one", "failure_rate": None},
        {"strategy": "B", "scenario": "one", "failure_rate": 0.2},
    ]

    report = rank_strategies(rows, metric="failure_rate")

    assert report["scenario_rankings"][0]["metric_means"]["A"] == pytest.approx(0.1)


def test_rank_strategies_rejects_unknown_metric():
    with pytest.raises(ValueError, match="unknown metric"):
        rank_strategies(
            [
                {"strategy": "A", "scenario": "one"},
                {"strategy": "B", "scenario": "one"},
            ],
            metric="not_a_metric",
        )


def test_rank_strategies_rejects_scenario_missing_a_strategy_metric():
    rows = [
        {"strategy": "A", "scenario": "one", "failure_rate": 0.1},
        {"strategy": "B", "scenario": "one", "failure_rate": 0.2},
        {"strategy": "A", "scenario": "two", "failure_rate": 0.1},
    ]

    with pytest.raises(ValueError, match="scenario 'two'"):
        rank_strategies(rows, metric="failure_rate")


def test_rank_strategies_ignores_strategies_outside_requested_scenarios():
    rows = [
        {"strategy": "A", "scenario": "chosen", "failure_rate": 0.1},
        {"strategy": "B", "scenario": "chosen", "failure_rate": 0.2},
        {"strategy": "C", "scenario": "unrelated", "failure_rate": 0.01},
    ]

    report = rank_strategies(
        rows,
        metric="failure_rate",
        scenarios=["chosen"],
    )

    assert report["scenarios"] == ["chosen"]
    assert [item["strategy"] for item in report["overall_rankings"]] == [
        "A",
        "B",
    ]
