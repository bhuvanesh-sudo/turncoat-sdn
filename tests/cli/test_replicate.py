"""``turncoat replicate``: paired runs into one results CSV, with a mean and CI per metric."""

from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from turncoat_sdn.cli.common import EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.replicate import METRIC_LABELS, replicate_rows
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.run import record_run
from turncoat_sdn.events import read_events
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.scoring.strategy_benchmark import SCENARIOS as BENCHMARK_SCENARIOS
from turncoat_sdn.sim import SCENARIOS, SimConfig, as_rows
from turncoat_sdn.stats import RESULT_METRICS, RESULTS_FIELDS, detection_columns, read_results

SHORT = replace(SimConfig(), sim_s=20.0)
ARGS = (
    "replicate",
    "--strategies",
    "zt_sdn,round_robin",
    "--scenarios",
    "clean,grayhole",
    "--seeds",
    "3",
    "--first-seed",
    "5",
    "--duration",
    "20",
    "--resamples",
    "500",
)


@pytest.fixture(scope="module")
def rows():
    return replicate_rows(
        strategies=["zt_sdn", "round_robin"],
        scenarios=["clean", "both"],
        seeds=[5, 6],
        config=SHORT,
    )


class TestRows:
    def test_one_row_per_run_ordered_by_scenario_seed_strategy(self, rows):
        assert [(r["scenario"], r["seed"], r["strategy"]) for r in rows] == [
            ("clean", 5, "zt_sdn"),
            ("clean", 5, "round_robin"),
            ("clean", 6, "zt_sdn"),
            ("clean", 6, "round_robin"),
            ("both", 5, "zt_sdn"),
            ("both", 5, "round_robin"),
            ("both", 6, "zt_sdn"),
            ("both", 6, "round_robin"),
        ]
        assert all(tuple(r) == RESULTS_FIELDS for r in rows)

    def test_each_row_is_the_run_and_its_score(self, rows, tmp_path):
        # The same run through `turncoat run`, its file read back and scored.
        path = tmp_path / "run.jsonl"
        run = record_run(path, strategy="zt_sdn", scenario="both", seed=6, config=SHORT)
        expected = {**as_rows([run])[0], **detection_columns(score_run(read_events(path)))}
        assert rows[6] == expected
        assert rows[6]["attackers"] == 2 and rows[6]["detection_rate"] == 1.0

    def test_clean_runs_have_nothing_to_detect(self, rows):
        assert {r["detection_rate"] for r in rows if r["scenario"] == "clean"} == {None}

    def test_strategies_share_a_workload_per_seed(self, rows):
        offered = {}
        for r in rows:
            offered.setdefault((r["scenario"], r["seed"]), set()).add(r["offered"])
        assert all(len(v) == 1 for v in offered.values())

    def test_rejects_unknown_names(self):
        with pytest.raises(ValueError, match="strategy"):
            replicate_rows(strategies=["nope"], scenarios=["clean"], seeds=[1])
        with pytest.raises(ValueError, match="scenario"):
            replicate_rows(strategies=["zt_sdn"], scenarios=["nope"], seeds=[1])


class TestCommand:
    def test_writes_the_results_and_prints_every_metric_with_an_interval(self, turncoat, tmp_path):
        out, summary = tmp_path / "results.csv", tmp_path / "summary.csv"
        code, printed = turncoat(*ARGS, "-o", str(out), "--summary", str(summary))
        assert code == EXIT_OK

        results = read_results(out)
        assert len(results) == 2 * 2 * 3
        assert {r["seed"] for r in results} == {5, 6, 7}

        assert "Ran 12 runs (2 strategies x 2 scenarios x 3 seeds, 5 to 7)" in printed
        assert "95% bootstrap confidence interval" in printed
        for label, _ in METRIC_LABELS.values():
            assert label in printed
        grayhole = printed[printed.index("grayhole  (3 seeds") :]
        slo = next(line for line in grayhole.splitlines() if "SLO violations" in line)
        assert slo.count("[") == 2 and slo.count("]") == 2

        with open(summary, newline="", encoding="utf-8") as f:
            intervals = list(csv.DictReader(f))
        assert len(intervals) == 2 * 2 * len(RESULT_METRICS)
        for row in intervals:
            if row["mean"]:
                assert float(row["ci_low"]) <= float(row["mean"]) <= float(row["ci_high"])

    def test_same_arguments_same_file(self, turncoat, tmp_path):
        first, second = tmp_path / "a.csv", tmp_path / "b.csv"
        assert turncoat(*ARGS, "-q", "-o", str(first)) == (EXIT_OK, "")
        assert turncoat(*ARGS, "-q", "-o", str(second)) == (EXIT_OK, "")
        assert first.read_bytes() == second.read_bytes()

    def test_onset_reaches_the_runs(self, turncoat, tmp_path):
        out = tmp_path / "late.csv"
        late = ("--scenarios", "grayhole", "--onset", "30", "--duration", "20")
        code, _ = turncoat("replicate", "--seeds", "1", *late, "-q", "-o", str(out))
        assert code == EXIT_OK
        # The run ends before the onset, so the grayhole never turns.
        for row in read_results(out):
            assert row["malicious_share"] == 0.0
            assert row["time_to_isolate_s"] is None

    @pytest.mark.parametrize(
        "bad",
        [
            ("--strategies", "zt_sdn,nope"),
            ("--scenarios", ""),
            ("--seeds", "0"),
            ("--confidence", "1.5"),
            ("--resamples", "0"),
        ],
    )
    def test_usage_errors(self, turncoat, tmp_path, bad):
        code, _ = turncoat("replicate", *bad, "-o", str(tmp_path / "x.csv"))
        assert code == 2

    def test_unwritable_output(self, turncoat, tmp_path):
        folder = tmp_path / "taken"
        folder.mkdir()
        code, printed = turncoat(*ARGS, "--seeds", "1", "-o", str(folder))
        assert code == EXIT_UNREADABLE
        assert "cannot write" in printed

    def test_defaults_cover_every_strategy_and_scenario(self):
        from turncoat_sdn.cli import build_parser

        args = build_parser().parse_args(["replicate"])
        assert args.strategies == list(STRATEGIES)
        assert args.scenarios == list(SCENARIOS)
        assert (args.seeds, args.first_seed, args.confidence) == (30, 1, 0.95)


def test_the_strategy_benchmark_runs_every_scenario():
    assert BENCHMARK_SCENARIOS == SCENARIOS
