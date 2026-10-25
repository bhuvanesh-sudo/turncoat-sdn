"""Tests for ``turncoat compare``."""

from __future__ import annotations

import csv

import pytest

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.replicate import replicate_rows
from turncoat_sdn.stats import write_results


@pytest.fixture
def results_file(tmp_path):
    """Create a small, paired results file using the real results writer."""
    rows = replicate_rows(
        strategies=["zt_sdn", "round_robin"],
        scenarios=["sybil"],
        seeds=[1, 2, 3],
    )
    path = tmp_path / "results.csv"
    write_results(rows, path)
    return path


class TestCompareCommand:
    def test_writes_comparison_csv(self, turncoat, results_file, tmp_path):
        output = tmp_path / "reports" / "comparisons.csv"
        code, printed = turncoat(
            "compare",
            str(results_file),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
            "-o",
            str(output),
        )

        assert code == EXIT_OK
        assert "Wrote" in printed
        with output.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        assert rows[0]["strategy_a"] == "zt_sdn"
        assert rows[0]["strategy_b"] == "round_robin"
        assert rows[0]["metric"] == "slo_violation_rate"
        assert rows[0]["adjusted_p_value"] != ""

    def test_quiet_mode(self, turncoat, results_file, tmp_path):
        code, printed = turncoat(
            "compare",
            str(results_file),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
            "-o",
            str(tmp_path / "quiet.csv"),
            "-q",
        )
        assert code == EXIT_OK
        assert printed == ""

    def test_missing_input_is_unreadable(self, turncoat, tmp_path):
        code, printed = turncoat(
            "compare",
            str(tmp_path / "missing.csv"),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
        )
        assert code == EXIT_UNREADABLE
        assert "cannot read" in printed

    def test_invalid_results_file_is_rejected(self, turncoat, tmp_path):
        path = tmp_path / "invalid.csv"
        path.write_text("not,a,results,file\n", encoding="utf-8")
        code, printed = turncoat(
            "compare",
            str(path),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
        )
        assert code == EXIT_FAILED
        assert "invalid results file" in printed

    def test_missing_strategy_in_results_is_rejected(self, turncoat, tmp_path):
        rows = replicate_rows(
            strategies=["zt_sdn"],
            scenarios=["sybil"],
            seeds=[1, 2],
        )
        path = tmp_path / "one-strategy.csv"
        write_results(rows, path)

        code, printed = turncoat(
            "compare",
            str(path),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
        )
        assert code == EXIT_FAILED
        assert "no rows found" in printed

    def test_unknown_strategy_is_a_usage_error(self, turncoat, results_file, tmp_path):
        code, _ = turncoat(
            "compare",
            str(results_file),
            "--strategies",
            "zt_sdn,unknown",
            "-o",
            str(tmp_path / "out.csv"),
        )
        assert code == 2

    def test_invalid_alpha_is_a_usage_error(self, turncoat, results_file):
        code, _ = turncoat("compare", str(results_file), "--alpha", "1.0")
        assert code == 2

    def test_unwritable_output_is_unreadable(self, turncoat, results_file, tmp_path):
        output_dir = tmp_path / "as-directory"
        output_dir.mkdir()
        code, printed = turncoat(
            "compare",
            str(results_file),
            "--strategies",
            "zt_sdn,round_robin",
            "--scenarios",
            "sybil",
            "--metrics",
            "slo_violation_rate",
            "-o",
            str(output_dir),
        )
        assert code == EXIT_UNREADABLE
        assert "cannot write" in printed
