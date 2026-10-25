"""Tests for comparison-report CSV export."""

import csv

from turncoat_sdn.stats.compare import compare_strategies
from turncoat_sdn.stats.report import (
    COMPARISON_FIELDS,
    comparison_rows,
    write_comparison_report,
)


def make_report():
    rows = []
    observations = {
        "baseline": [0.40, 0.35, 0.45, 0.30],
        "zero_trust": [0.10, 0.12, 0.15, 0.08],
    }
    for strategy, values in observations.items():
        for seed, value in enumerate(values, start=1):
            rows.append(
                {
                    "strategy": strategy,
                    "scenario": "sybil",
                    "seed": seed,
                    "slo_violation_rate": value,
                }
            )
    return compare_strategies(
        rows,
        strategies=["baseline", "zero_trust"],
        scenarios=["sybil"],
        metrics=["slo_violation_rate"],
    )


def test_comparison_rows_include_adjustment_and_decision():
    report = make_report()
    rows = comparison_rows(report)

    assert len(rows) == 1
    assert tuple(rows[0]) == COMPARISON_FIELDS
    assert rows[0]["strategy_a"] == "baseline"
    assert rows[0]["strategy_b"] == "zero_trust"
    assert rows[0]["n_pairs"] == 4
    assert rows[0]["p_value"] <= rows[0]["adjusted_p_value"] <= 1.0
    assert rows[0]["alpha"] == report.alpha
    assert isinstance(rows[0]["significant"], bool)


def test_writer_creates_parent_directories_and_round_trips(tmp_path):
    report = make_report()
    output = tmp_path / "nested" / "reports" / "comparison.csv"

    count = write_comparison_report(report, output)

    assert count == 1
    with output.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == COMPARISON_FIELDS
        records = list(reader)

    assert len(records) == 1
    record = records[0]
    assert record["strategy_a"] == "baseline"
    assert record["strategy_b"] == "zero_trust"
    assert record["scenario"] == "sybil"
    assert record["metric"] == "slo_violation_rate"
    assert int(record["n_pairs"]) == 4
    assert float(record["adjusted_p_value"]) >= float(record["p_value"])
    assert record["significant"] in ("True", "False")


def test_writer_replaces_existing_file(tmp_path):
    report = make_report()
    output = tmp_path / "comparison.csv"
    output.write_text("old content\n", encoding="utf-8")

    count = write_comparison_report(report, output)

    assert count == 1
    assert "old content" not in output.read_text(encoding="utf-8")


def test_writer_returns_number_of_exported_comparisons(tmp_path):
    report = compare_strategies(
        [
            {"strategy": "a", "scenario": "s", "seed": 1, "m": 1.0},
            {"strategy": "a", "scenario": "s", "seed": 2, "m": 2.0},
            {"strategy": "b", "scenario": "s", "seed": 1, "m": 0.5},
            {"strategy": "b", "scenario": "s", "seed": 2, "m": 1.0},
            {"strategy": "c", "scenario": "s", "seed": 1, "m": 0.2},
            {"strategy": "c", "scenario": "s", "seed": 2, "m": 0.4},
        ],
        strategies=["a", "b", "c"],
        scenarios=["s"],
        metrics=["m"],
    )

    assert write_comparison_report(report, tmp_path / "all.csv") == 3
