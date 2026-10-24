"""Tests for descriptive strategy comparison reports."""

import csv
import json

import pytest

from turncoat_sdn.scoring.benchmark import BenchmarkSummary
from turncoat_sdn.scoring.comparison_report import (
    compare_summaries,
    load_summaries,
    write_comparison_report,
)


def summary(name, detection, false_positive, latency):
    return BenchmarkSummary(
        name=name,
        runs=2,
        attack_subjects=10,
        detected_attacks=8,
        missed_attacks=2,
        detection_rate=detection,
        honest_subjects=10,
        false_positives=1,
        false_positive_rate=false_positive,
        mean_detection_latency_s=latency,
    )


def test_comparison_identifies_observed_leaders_and_ties():
    report = compare_summaries(
        [
            summary("random", 0.8, 0.2, 3.0),
            summary("zt_sdn", 0.9, 0.1, 2.0),
            summary("least_conn", 0.9, 0.1, 2.5),
        ]
    )

    assert report[0]["metric"] == "detection_rate"
    assert report[0]["leaders"] == ["zt_sdn", "least_conn"]
    assert report[1]["leaders"] == ["zt_sdn", "least_conn"]
    assert report[2]["leaders"] == ["zt_sdn"]
    assert report[0]["best_value"] == 0.9


def test_missing_metrics_are_explicit():
    report = compare_summaries(
        [
            summary("random", None, None, None),
            summary("zt_sdn", None, None, None),
        ]
    )

    assert all(item["best_value"] is None for item in report)
    assert all(item["leaders"] == [] for item in report)
    assert all(item["strategies_without_value"] == ["random", "zt_sdn"] for item in report)


def test_json_input_and_json_csv_exports(tmp_path):
    source = tmp_path / "summary.json"
    source.write_text(
        json.dumps(
            [
                {
                    "name": "zt_sdn",
                    "runs": 1,
                    "attack_subjects": 1,
                    "detected_attacks": 1,
                    "missed_attacks": 0,
                    "detection_rate": 1.0,
                    "honest_subjects": 1,
                    "false_positives": 0,
                    "false_positive_rate": 0.0,
                    "mean_detection_latency_s": 1.5,
                }
            ]
        ),
        encoding="utf-8",
    )

    summaries = load_summaries(source)
    assert summaries[0].name == "zt_sdn"

    report = compare_summaries(summaries)
    json_path = tmp_path / "out" / "comparison.json"
    csv_path = tmp_path / "out" / "comparison.csv"
    write_comparison_report(report, json_path, csv_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["leaders"] == ["zt_sdn"]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["strategy"] == "zt_sdn"
    assert rows[0]["is_observed_leader"] == "True"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not-json", "Invalid benchmark JSON"),
        ('{"not":"a list"}', "must contain a list"),
        ("[42]", "must be an object"),
        ('[{"name":"missing fields"}]', "is missing fields"),
    ],
)
def test_invalid_input_is_rejected(tmp_path, contents, message):
    path = tmp_path / "invalid.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_summaries(path)
