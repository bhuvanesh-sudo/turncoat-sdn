"""The replicate results file: its columns, detection columns, and a matching writer and reader."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from turncoat_sdn.sim import CSV_FIELDS, METRICS
from turncoat_sdn.stats import (
    RESULT_METRICS,
    RESULTS_FIELDS,
    RESULTS_VERSION,
    detection_columns,
    read_results,
    results_row,
    write_results,
)


def subject(truth, predicted, latency=None):
    return SimpleNamespace(
        truth=truth,
        predicted=predicted,
        correct=truth == predicted,
        detection_latency_s=latency,
    )


SIM_ROW = {
    "strategy": "zt_sdn",
    "scenario": "both",
    "seed": 1,
    "offered": 7624,
    "completed": 7609,
    "failed": 5,
    "slo_violation_rate": 0.116264,
    "failure_rate": 0.000656,
    "malicious_share": 0.004591,
    "mean_latency_ms": 240.012,
    "p95_latency_ms": 684.942,
    "gini": 0.2501,
    "time_to_isolate_s": 3.0,
}


class TestColumns:
    def test_starts_with_the_simulators_row(self):
        assert RESULTS_FIELDS[: len(CSV_FIELDS)] == CSV_FIELDS

    def test_every_metric_is_a_column_and_agrees_with_the_simulator(self):
        assert set(RESULT_METRICS) <= set(RESULTS_FIELDS)
        for name, lower_is_better in METRICS.items():
            assert RESULT_METRICS[name] is lower_is_better

    def test_version(self):
        assert RESULTS_VERSION == "1.0"


class TestDetectionColumns:
    def test_counts_rates_and_latency(self):
        columns = detection_columns(
            [
                subject("sybil", "sybil", 3.0),
                subject("blackhole", "blackhole", 5.0),
                subject("grayhole", "blackhole", 4.0),  # wrong label: not named
                subject("none", "none"),
                subject("none", "sybil"),  # an honest server mislabelled
                subject("none", "none"),
                subject("none", "none"),
            ]
        )
        assert columns == {
            "attackers": 3,
            "attackers_named": 2,
            "detection_rate": 0.666667,
            "mean_detection_latency_s": 4.0,
            "honest_subjects": 4,
            "honest_mislabelled": 1,
            "false_positive_rate": 0.25,
        }

    def test_nothing_to_detect_is_blank_not_zero(self):
        columns = detection_columns([subject("none", "none")])
        assert columns["detection_rate"] is None
        assert columns["mean_detection_latency_s"] is None
        assert columns["false_positive_rate"] == 0.0

    def test_latency_skips_unknown_onsets(self):
        columns = detection_columns([subject("sybil", "sybil", None), subject("drop", "drop", 2)])
        assert columns["mean_detection_latency_s"] == 2.0


class TestFile:
    def rows(self):
        row = results_row(SIM_ROW, [subject("sybil", "sybil", 3.0), subject("none", "none")])
        clean = results_row(
            {**SIM_ROW, "scenario": "clean", "time_to_isolate_s": ""}, [subject("none", "none")]
        )
        return [row, clean]

    def test_results_row_is_in_column_order(self):
        assert tuple(self.rows()[0]) == RESULTS_FIELDS

    def test_results_row_needs_every_simulator_column(self):
        with pytest.raises(ValueError, match="gini"):
            results_row({k: v for k, v in SIM_ROW.items() if k != "gini"}, [])

    def test_round_trip_with_types_and_blanks(self, tmp_path):
        path = tmp_path / "out" / "results.csv"
        assert write_results(self.rows(), path) == 2
        back = read_results(path)
        assert back[0] == {**self.rows()[0]}
        assert isinstance(back[0]["seed"], int) and isinstance(back[0]["gini"], float)
        clean = back[1]
        assert clean["time_to_isolate_s"] is None
        assert clean["detection_rate"] is None
        assert clean["attackers"] == 0

    def test_header_is_the_columns(self, tmp_path):
        path = tmp_path / "results.csv"
        write_results(self.rows(), path)
        assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(RESULTS_FIELDS)

    def test_rejects_a_file_that_is_not_a_results_file(self, tmp_path):
        path = tmp_path / "other.csv"
        path.write_text("name,value\na,1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not a turncoat results file"):
            read_results(path)

    def test_rejects_a_cell_that_does_not_parse(self, tmp_path):
        path = tmp_path / "results.csv"
        write_results(self.rows(), path)
        text = path.read_text(encoding="utf-8").replace("7624", "lots", 1)
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="line 2.*offered"):
            read_results(path)

    def test_keeps_columns_a_newer_version_adds(self, tmp_path):
        path = tmp_path / "results.csv"
        write_results(self.rows(), path)
        lines = path.read_text(encoding="utf-8").splitlines()
        lines = [lines[0] + ",energy_j"] + [line + ",12.5" for line in lines[1:]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert read_results(path)[0]["energy_j"] == "12.5"
