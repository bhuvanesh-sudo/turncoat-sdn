"""``examples/custom_strategy.py``: a new strategy in under 50 lines, run as a user would."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import EventList, read_events
from turncoat_sdn.events.validate import validate_file

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parents[1] / "examples" / "custom_strategy.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def example():
    return load("custom_strategy", EXAMPLE)


def test_under_50_lines_of_code():
    # The same counter the custom attack example is held to.
    counter = load("_attack_example_test", HERE / "test_custom_attack.py").code_lines
    assert counter(EXAMPLE.read_text(encoding="utf-8")) < 50


class TestGatedRoundRobin:
    def choose(self, example, trust, anomaly, calls=1):
        router = example.gated_round_robin(len(trust), None)
        n = len(trust)
        return [router.choose(trust, [0.0] * n, [50.0] * n, anomaly) for _ in range(calls)]

    def test_cycles_like_round_robin_when_everyone_is_trusted(self, example):
        assert self.choose(example, [0.9] * 3, [0.0] * 3, calls=5) == [0, 1, 2, 0, 1]

    def test_skips_a_server_below_the_isolation_threshold(self, example):
        assert self.choose(example, [0.9, 0.2, 0.9], [0.0] * 3, calls=4) == [0, 2, 0, 2]

    def test_skips_a_server_at_the_anomaly_gate(self, example):
        assert self.choose(example, [0.9] * 3, [0.0, 0.0, 0.5], calls=3) == [0, 1, 0]

    def test_refuses_when_every_server_is_held_out(self, example):
        assert self.choose(example, [0.1, 0.1], [0.0, 0.0]) == [None]

    def test_each_run_gets_its_own_cycle(self, example):
        first = example.gated_round_robin(3, None)
        first.choose([0.9] * 3, [0.0] * 3, [50.0] * 3, [0.0] * 3)
        second = example.gated_round_robin(3, None)
        assert second.choose([0.9] * 3, [0.0] * 3, [50.0] * 3, [0.0] * 3) == 0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_beats_zt_sdn_on_slo_and_round_robin_on_failures(example, seed):
    """The finding the example prints, seed by seed on 'both'."""
    service = {}
    for strategy in ("gated_rr", "zt_sdn", "round_robin"):
        recording = EventList(backend="sim", seed=seed, strategy=strategy, scenario="both")
        example.run(strategy, seed, recording)
        service[strategy] = score_recording(recording.events)["service"]
    gated, zt, rr = service["gated_rr"], service["zt_sdn"], service["round_robin"]
    assert gated["slo_violation_rate"] < zt["slo_violation_rate"]
    assert gated["failure_rate"] < 0.01 < rr["failure_rate"]


def test_runs_as_a_script(tmp_path):
    recording = tmp_path / "gated.jsonl"
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--seeds", "2", "--record", str(recording)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "gated_rr against two built-ins on 'both'" in result.stdout
    assert result.stdout.count("Wilcoxon p =") == 4
    assert validate_file(recording).ok
    events = read_events(recording)
    assert events[0]["strategy"] == "gated_rr"
    truth = {s["subject"]: s["truth"] for s in score_recording(events)["subjects"]}
    assert (truth["srv7"], truth["srv8"]) == ("blackhole", "sybil")
