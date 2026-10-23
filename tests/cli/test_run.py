"""``turncoat run``: one seeded simulation, recorded to a valid ``events.jsonl``."""

from __future__ import annotations

from dataclasses import replace

import pytest

from turncoat_sdn.cli.common import EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.run import record_run
from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.sim import SCENARIOS, SimConfig, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = replace(SimConfig(), sim_s=25.0)
SHORT_SECONDS = "25"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_scenario_records_a_valid_file(tmp_path, scenario):
    # Every strategy is covered by tests/cli/test_score.py, which validates too.
    path = tmp_path / "run.jsonl"
    record_run(path, strategy="zt_sdn", scenario=scenario, seed=3, config=SHORT)
    report = validate_file(path)
    assert report.ok, report.format(str(path))


def test_recording_does_not_change_the_numbers(tmp_path):
    recorded = record_run(
        tmp_path / "run.jsonl", strategy="zt_sdn", scenario="both", seed=11, config=SHORT
    )
    plain = simulate(
        STRATEGIES["zt_sdn"],
        "both",
        11,
        config=SHORT,
        trust=SimTrustModel,
        latency_tell=latency_tell,
        name="zt_sdn",
    )
    assert recorded == plain


def test_header_says_how_the_run_was_made(tmp_path):
    path = tmp_path / "run.jsonl"
    record_run(path, strategy="least_conn", scenario="sybil", seed=42, config=SHORT)
    header = read_events(path)[0]
    assert header == {
        "type": "header",
        "schema_version": "1.0",
        "backend": "sim",
        "seed": 42,
        "strategy": "least_conn",
        "scenario": "sybil",
    }


def test_same_seed_same_file(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    for path in (a, b):
        record_run(path, strategy="random", scenario="drop", seed=5, config=SHORT)
    assert a.read_bytes() == b.read_bytes()


def test_unknown_names_are_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown strategy"):
        record_run(tmp_path / "x.jsonl", strategy="nope", scenario="both", seed=1)
    with pytest.raises(ValueError, match="unknown scenario"):
        record_run(tmp_path / "x.jsonl", strategy="zt_sdn", scenario="nope", seed=1)


class TestCommand:
    def test_defaults_write_run_jsonl(self, turncoat, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        code, out = turncoat("run", "--duration", SHORT_SECONDS)
        assert code == EXIT_OK
        assert (tmp_path / "run.jsonl").exists()
        assert "zt_sdn on both, seed 1" in out
        assert "Next: turncoat score run.jsonl" in out

    def test_options_reach_the_recording(self, turncoat, tmp_path):
        path = tmp_path / "out" / "rr.jsonl"
        code, _ = turncoat(
            "run",
            "--strategy",
            "round_robin",
            "--scenario",
            "drop",
            "--seed",
            "9",
            "--duration",
            SHORT_SECONDS,
            "-o",
            str(path),
        )
        assert code == EXIT_OK
        header = read_events(path)[0]
        assert (header["strategy"], header["scenario"], header["seed"]) == (
            "round_robin",
            "drop",
            9,
        )

    def test_duration_sets_simulated_time(self, turncoat, tmp_path):
        path = tmp_path / "run.jsonl"
        turncoat("run", "--duration", "10", "-o", str(path), "-q")
        last = read_events(path)[-1]
        assert last["ts"] <= 10.0 + 2.0  # the last outcomes land within one task timeout

    def test_quiet_prints_nothing(self, turncoat, tmp_path):
        code, out = turncoat("run", "--duration", "5", "-o", str(tmp_path / "r.jsonl"), "-q")
        assert code == EXIT_OK
        assert out == ""

    def test_unwritable_output_exits_2(self, turncoat, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("not a directory")
        code, out = turncoat("run", "--duration", "5", "-o", str(blocker / "run.jsonl"))
        assert code == EXIT_UNREADABLE
        assert "cannot write" in out

    @pytest.mark.parametrize(
        "args",
        [
            ("--strategy", "nope"),
            ("--scenario", "nope"),
            ("--seed", "-1"),
            ("--seed", "x"),
            ("--duration", "0"),
            ("--duration", "inf"),
        ],
    )
    def test_bad_options_are_usage_errors(self, turncoat, args):
        code, _ = turncoat("run", *args)
        assert code == 2
