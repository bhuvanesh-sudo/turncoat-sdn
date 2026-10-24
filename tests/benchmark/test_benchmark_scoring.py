"""Tests for the additive v0.3 benchmark scoring module."""

import csv
import json

from turncoat_sdn.scoring.attack_report import SubjectResult
from turncoat_sdn.scoring.benchmark import (
    summarize_results,
    write_csv,
    write_json,
)


def result(subject, truth, predicted, latency=None):
    return SubjectResult(
        subject=subject,
        kind="node",
        truth=truth,
        predicted=predicted,
        detection_latency_s=latency,
    )


def test_detection_and_false_positive_rates_are_aggregated():
    runs = [
        [
            result("attacker-1", "sybil", "sybil", 2.0),
            result("attacker-2", "blackhole", "none"),
            result("honest-1", "none", "sybil"),
            result("honest-2", "none", "none"),
        ]
    ]

    summary = summarize_results("zt_sdn", runs)

    assert summary.runs == 1
    assert summary.attack_subjects == 2
    assert summary.detected_attacks == 1
    assert summary.missed_attacks == 1
    assert summary.detection_rate == 0.5
    assert summary.honest_subjects == 2
    assert summary.false_positives == 1
    assert summary.false_positive_rate == 0.5
    assert summary.mean_detection_latency_s == 2.0


def test_unknown_latency_is_not_treated_as_zero():
    summary = summarize_results(
        "random",
        [[result("attacker-1", "sybil", "sybil", None)]],
    )

    assert summary.detected_attacks == 1
    assert summary.mean_detection_latency_s is None


def test_empty_input_returns_undefined_rates():
    summary = summarize_results("empty", [])

    assert summary.runs == 0
    assert summary.detection_rate is None
    assert summary.false_positive_rate is None
    assert summary.mean_detection_latency_s is None


def test_reports_round_trip_to_json_and_csv(tmp_path):
    summaries = [
        summarize_results(
            "zt_sdn",
            [[result("attacker-1", "sybil", "sybil", 1.5)]],
        )
    ]
    json_path = tmp_path / "reports" / "benchmark.json"
    csv_path = tmp_path / "reports" / "benchmark.csv"

    write_json(summaries, json_path)
    write_csv(summaries, csv_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data[0]["name"] == "zt_sdn"
    assert data[0]["detection_rate"] == 1.0

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["name"] == "zt_sdn"
    assert rows[0]["detected_attacks"] == "1"
