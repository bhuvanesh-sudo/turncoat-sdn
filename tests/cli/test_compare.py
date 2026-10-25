"""Tests for ``turncoat compare``."""

from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.compare import build_report, format_comparisons, paired_values
from turncoat_sdn.cli.replicate import METRIC_LABELS, replicate_rows
from turncoat_sdn.sim import SimConfig
from turncoat_sdn.stats import RESULT_METRICS, compare_strategies, holm_adjust, write_results
from turncoat_sdn.stats.bootstrap import paired_bootstrap_ci


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


@pytest.fixture(scope="module")
def short_rows():
    """Four paired seeds of two strategies, with and without attackers, 25 s each."""
    return replicate_rows(
        strategies=["zt_sdn", "least_conn"],
        scenarios=["both", "clean"],
        seeds=[1, 2, 3, 4],
        config=replace(SimConfig(), sim_s=25.0),
    )


@pytest.fixture
def short_file(tmp_path, short_rows):
    path = tmp_path / "results.csv"
    write_results(short_rows, path)
    return path


def _synthetic(margin: float, seeds: int = 12) -> list[dict]:
    """Rows where ``a`` beats ``b`` on SLO violations and attackers named on every seed."""
    rows = []
    for seed in range(1, seeds + 1):
        for strategy, slo, named in (("a", 0.1, 1.0), ("b", 0.1 + margin, 0.5)):
            rows.append(
                {
                    "strategy": strategy,
                    "scenario": "both",
                    "seed": seed,
                    "slo_violation_rate": slo + seed / 1000,
                    "detection_rate": named - seed / 1000,
                }
            )
    return rows


class TestBuildReport:
    """The comparison family behind the table."""

    def test_matches_compare_strategies_when_everything_is_measured(self, short_rows):
        args = (short_rows, ["zt_sdn", "least_conn"], ["both"], list(RESULT_METRICS))
        report, skipped = build_report(*args)
        assert skipped == []
        assert report == compare_strategies(*args)

    def test_unmeasurable_metrics_leave_the_family(self, short_rows):
        metrics = list(RESULT_METRICS)
        report, skipped = build_report(short_rows, ["zt_sdn", "least_conn"], ["clean"], metrics)
        left_out = {metric for _, metric, _, _ in skipped}
        assert {"time_to_isolate_s", "detection_rate", "mean_detection_latency_s"} <= left_out
        tested = [item.comparison.metric for item in report.comparisons]
        assert not left_out & set(tested)
        assert len(tested) + len(skipped) == len(metrics)

    def test_one_holm_family_across_scenarios(self, short_rows):
        report, _ = build_report(
            short_rows, ["zt_sdn", "least_conn"], ["both", "clean"], list(RESULT_METRICS)
        )
        raw = [item.comparison.p_value for item in report.comparisons]
        assert [item.adjusted_p_value for item in report.comparisons] == list(holm_adjust(raw))

    def test_missing_strategy_is_named(self, short_rows):
        with pytest.raises(ValueError, match="no rows found for 'no_trust' in scenario 'both'"):
            build_report(short_rows, ["zt_sdn", "no_trust"], ["both"], ["gini"])

    def test_needs_two_strategies(self, short_rows):
        with pytest.raises(ValueError, match="at least two"):
            build_report(short_rows, ["zt_sdn"], ["both"], ["gini"])

    def test_paired_values_skip_seeds_with_a_blank(self):
        rows = _synthetic(0.2, seeds=3)
        rows[0]["slo_violation_rate"] = None
        a, b = paired_values(rows, "a", "b", "both", "slo_violation_rate")
        assert len(a) == len(b) == 2


class TestTable:
    def test_each_metric_has_means_interval_p_and_holm_p(self, short_rows):
        report, skipped = build_report(
            short_rows, ["zt_sdn", "least_conn"], ["both"], list(RESULT_METRICS)
        )
        text = format_comparisons(report, short_rows, skipped)
        assert "both: zt_sdn vs least_conn  (4 paired seeds)" in text
        for column in ("Difference [95% CI]", "p", "Holm p", "Better"):
            assert column in text
        for label, _ in METRIC_LABELS.values():
            assert label in text
        assert f"adjusted across all {len(RESULT_METRICS)} tests" in text

    def test_numbers_come_from_the_stats_package(self, short_rows):
        report, _ = build_report(short_rows, ["zt_sdn", "least_conn"], ["both"], ["gini"])
        line = next(
            line
            for line in format_comparisons(report, short_rows).splitlines()
            if "Load Gini" in line
        )
        interval = paired_bootstrap_ci(short_rows, "zt_sdn", "least_conn", "both", "gini")
        a, b = paired_values(short_rows, "zt_sdn", "least_conn", "both", "gini")
        assert f"{sum(a) / len(a):.3f}" in line
        assert f"{sum(b) / len(b):.3f}" in line
        assert f"{interval.mean:+.3f} [{interval.low:+.3f}, {interval.high:+.3f}]" in line
        assert f"{report.comparisons[0].comparison.p_value:.4f}" in line

    def test_better_names_the_winner_in_each_metrics_direction(self):
        rows = _synthetic(0.2)
        report, skipped = build_report(
            rows, ["a", "b"], ["both"], ["slo_violation_rate", "detection_rate"]
        )
        assert all(item.significant for item in report.comparisons)
        lines = format_comparisons(report, rows, skipped).splitlines()
        slo = next(line for line in lines if "SLO violations" in line)
        named = next(line for line in lines if "Attackers named" in line)
        # a has fewer SLO violations (lower is better) and names more attackers
        # (higher is better), so it wins both though the differences differ in sign.
        assert slo.rstrip().endswith(" a")
        assert named.rstrip().endswith(" a")

    def test_no_winner_without_significance(self):
        rows = _synthetic(0.2, seeds=4)  # the smallest p with 4 pairs is 0.125
        report, skipped = build_report(rows, ["a", "b"], ["both"], ["slo_violation_rate"])
        line = format_comparisons(report, rows, skipped).splitlines()[2]
        assert line.rstrip().endswith("-")

    def test_skipped_cells_are_listed(self, short_rows):
        report, skipped = build_report(
            short_rows, ["zt_sdn", "least_conn"], ["clean"], list(RESULT_METRICS)
        )
        text = format_comparisons(report, short_rows, skipped)
        assert "Not compared" in text
        assert "clean: time_to_isolate_s, detection_rate, mean_detection_latency_s" in text


class TestTableCommand:
    def test_default_metrics_on_a_clean_scenario_compare(self, turncoat, short_file, tmp_path):
        # Time to isolate is blank on every clean run; this used to stop the command.
        code, printed = turncoat("compare", str(short_file), "-o", str(tmp_path / "c.csv"))
        assert code == EXIT_OK
        assert "clean: zt_sdn vs least_conn" in printed
        assert "Not compared" in printed

    def test_prints_the_table_and_writes_the_report(self, turncoat, short_file, tmp_path):
        output = tmp_path / "c.csv"
        code, printed = turncoat(
            "compare", str(short_file), "--scenarios", "both", "-o", str(output)
        )
        assert code == EXIT_OK
        assert "both: zt_sdn vs least_conn  (4 paired seeds)" in printed
        assert "Holm p" in printed
        assert f"Wrote {output} ({len(RESULT_METRICS)} comparisons" in printed
        with output.open(newline="", encoding="utf-8") as stream:
            assert len(list(csv.DictReader(stream))) == len(RESULT_METRICS)

    def test_confidence_and_resamples_reach_the_table(self, turncoat, short_file, tmp_path):
        code, printed = turncoat(
            "compare",
            str(short_file),
            "--scenarios",
            "both",
            "--confidence",
            "0.9",
            "--resamples",
            "500",
            "-o",
            str(tmp_path / "c.csv"),
        )
        assert code == EXIT_OK
        assert "Difference [90% CI]" in printed
        assert "500 resamples" in printed

    def test_same_file_same_table(self, turncoat, short_file, tmp_path):
        args = ("compare", str(short_file), "-o", str(tmp_path / "c.csv"))
        assert turncoat(*args)[1] == turncoat(*args)[1]

    @pytest.mark.parametrize(
        "args", [("--confidence", "1"), ("--confidence", "95"), ("--resamples", "0")]
    )
    def test_bad_interval_options_are_usage_errors(self, turncoat, short_file, args):
        code, _ = turncoat("compare", str(short_file), *args)
        assert code == 2
