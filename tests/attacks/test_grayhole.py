"""The grayhole: on its own, in the simulator, and named by the attack scorer.

It drops a configurable fraction of the tasks it accepts once it turns. These
pin that the fraction is honoured, that nothing is dropped before ``start_s``,
that its draws are seeded and leave the paired workload alone, that its
recording validates, and that the scorer names it ``grayhole``.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import replace

import pytest

from turncoat_sdn.attacks import Grayhole
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import SCENARIOS, SimConfig, as_rows, malicious_roles, scenario_attacks
from turncoat_sdn.sim import simulate as _simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = SimConfig(sim_s=60.0, n_nodes=6)
ONSET = 20.0
DELAYED = replace(SHORT, attack_start_s=ONSET)
HOOKS = {"trust": SimTrustModel, "latency_tell": latency_tell}


def round_robin(n, rng):
    """Keeps feeding every node, so the grayhole sees traffic all run."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def simulate(scenario, seed=3, config=SHORT, **kwargs):
    return _simulate(round_robin, scenario, seed, config=config, **HOOKS, **kwargs)


def record(tmp_path, scenario="grayhole", seed=3, config=DELAYED, **kwargs):
    path = tmp_path / "run.jsonl"
    with EventWriter(path, backend="sim", seed=seed, strategy="rr", scenario=scenario) as rec:
        run = simulate(scenario, seed, config, recorder=rec, **kwargs)
    return run, read_events(path), path


def reports(events, node):
    return [ev for ev in events if ev["type"] == "report" and ev["node"] == node]


class Counting(Grayhole):
    """A grayhole that notes every task it is asked to serve, for the tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def serve(self, now, demand_s, rng):
        served = super().serve(now, demand_s, rng)
        self.calls.append((now, served))
        return served


class TestProfile:
    def test_label_and_defaults(self):
        attack = Grayhole()
        assert attack.name == "grayhole"
        assert (attack.start_s, attack.drop_fraction) == (0.0, 0.5)
        assert attack.ground_truth() == {"attack": "grayhole", "attack_start_s": 0.0}

    @pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan"), "0.5", None])
    def test_rejects_a_bad_fraction(self, bad):
        with pytest.raises(ValueError, match="drop_fraction"):
            Grayhole(drop_fraction=bad)

    def test_honest_before_onset_and_draws_nothing(self):
        rng = random.Random(0)
        state = rng.getstate()
        attack = Grayhole(start_s=10.0, drop_fraction=1.0)
        assert attack.service_time(9.999, 0.2, rng) == 0.2
        assert rng.getstate() == state

    @pytest.mark.parametrize("fraction", [0.1, 0.3, 0.5, 0.8])
    def test_drops_the_configured_fraction(self, fraction):
        attack = Grayhole(drop_fraction=fraction)
        rng = random.Random(42)
        draws = [attack.service_time(1.0, 0.2, rng) for _ in range(10_000)]
        dropped = sum(d is None for d in draws) / len(draws)
        assert dropped == pytest.approx(fraction, abs=0.02)
        # What it does not drop it serves honestly.
        assert {d for d in draws if d is not None} == {0.2}

    def test_the_ends_of_the_range(self):
        rng = random.Random(1)
        assert all(Grayhole(drop_fraction=0.0).serve(1.0, 0.2, rng) == 0.2 for _ in range(200))
        assert all(Grayhole(drop_fraction=1.0).serve(1.0, 0.2, rng) is None for _ in range(200))

    def test_one_draw_per_task_whatever_the_fraction(self):
        # So two grayholes on one seed stay aligned task for task.
        a, b = random.Random(5), random.Random(5)
        Grayhole(drop_fraction=0.0).serve(1.0, 0.2, a)
        Grayhole(drop_fraction=1.0).serve(1.0, 0.2, b)
        assert a.getstate() == b.getstate()

    def test_reports_honestly(self):
        from turncoat_sdn.attacks import Status

        honest = Status(0.5, 51.0)
        assert Grayhole().status(5.0, honest, 1.0, random.Random(0)) == honest

    def test_repr(self):
        assert (
            repr(Grayhole(12.5, drop_fraction=0.25)) == "Grayhole(start_s=12.5, drop_fraction=0.25)"
        )


class TestScenario:
    def test_is_a_built_in_scenario(self):
        assert "grayhole" in SCENARIOS
        assert SCENARIOS[:4] == ("clean", "sybil", "drop", "both")  # FYP order kept

    def test_takes_its_settings_from_the_config(self):
        cfg = replace(DELAYED, grayhole_drop_fraction=0.3)
        attacks = scenario_attacks("grayhole", cfg)
        assert set(attacks) == {5}
        attack = attacks[5]
        assert isinstance(attack, Grayhole)
        assert (attack.start_s, attack.drop_fraction) == (ONSET, 0.3)
        assert malicious_roles("grayhole", 8) == {7: "grayhole"}

    def test_the_scenario_equals_passing_the_attack(self):
        by_name = simulate("grayhole")
        by_object = simulate("clean", attacks={5: Grayhole()})
        assert by_object.latencies_ms == by_name.latencies_ms
        assert as_rows([by_object])[0] == {**as_rows([by_name])[0], "scenario": "clean"}


class TestInTheSimulator:
    @pytest.mark.parametrize("fraction", [0.3, 0.5, 0.7])
    def test_the_fraction_is_honoured(self, fraction):
        # Dropped tasks hold their workers, so fewer reach serve: run longer.
        attack = Counting(ONSET, drop_fraction=fraction)
        simulate("clean", config=replace(SHORT, sim_s=120.0), attacks={5: attack})
        assert len(attack.calls) > 200
        dropped = sum(served is None for _, served in attack.calls) / len(attack.calls)
        assert dropped == pytest.approx(fraction, abs=0.08)

    def test_nothing_is_dropped_before_onset(self, tmp_path):
        attack = Counting(ONSET)
        _, events, _ = record(tmp_path, "clean", attacks={5: attack})
        # serve is only ever asked after the onset...
        assert attack.calls and min(now for now, _ in attack.calls) >= ONSET
        # ...and the recording agrees: every task finished before it succeeded,
        # and the first timeout is a client giving up on a post-onset task.
        mine = reports(events, "srv6")
        before = [r for r in mine if r["ts"] < ONSET]
        timeouts = [r for r in mine if r["status"] == "timeout"]
        assert before and all(r["status"] == "success" for r in before)
        assert timeouts and min(r["ts"] for r in timeouts) >= ONSET + SHORT.task_timeout_s

    def test_it_is_gray_not_black(self, tmp_path):
        _, events, _ = record(tmp_path)
        after = [r for r in reports(events, "srv6") if r["ts"] >= ONSET + SHORT.task_timeout_s]
        statuses = {r["status"] for r in after}
        assert statuses == {"success", "timeout"}

    def test_drops_are_seeded(self):
        first = simulate("grayhole", config=DELAYED)
        second = simulate("grayhole", config=DELAYED)
        assert as_rows([first]) == as_rows([second])
        assert first.latencies_ms == second.latencies_ms
        other = simulate("grayhole", seed=4, config=DELAYED)
        assert other.failed != first.failed

    def test_its_draws_do_not_shift_the_workload(self):
        assert simulate("grayhole", config=DELAYED).offered == simulate("clean").offered

    def test_the_recording_validates_and_carries_the_ground_truth(self, tmp_path):
        _, events, path = record(tmp_path)
        assert validate_file(path).ok
        nodes = {node["id"]: node for node in events[1]["graph"]["nodes"]}
        assert (nodes["srv6"]["attack"], nodes["srv6"]["attack_start_s"]) == ("grayhole", ONSET)
        assert events[1]["config"]["grayhole_drop_fraction"] == SHORT.grayhole_drop_fraction


def score_zt_sdn(tmp_path, seed, onset):
    path = tmp_path / f"zt-{seed}-{onset:g}.jsonl"
    cfg = SimConfig(attack_start_s=onset)
    with EventWriter(path, backend="sim", seed=seed, scenario="grayhole") as rec:
        run = _simulate(STRATEGIES["zt_sdn"], "grayhole", seed, config=cfg, recorder=rec, **HOOKS)
    assert validate_file(path).ok
    return run, {r.subject: r for r in score_run(read_events(path))}["srv8"]


class TestTheScorerNamesIt:
    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
    def test_hostile_from_the_start(self, tmp_path, seed):
        run, result = score_zt_sdn(tmp_path, seed, 0.0)
        assert run.time_to_isolate_s is not None
        assert result.truth == "grayhole"
        assert result.predicted == "grayhole"
        assert result.correct
        assert 0.0 < result.detection_latency_s <= 6.0

    @pytest.mark.parametrize("seed", [1000, 1001, 1002, 1003, 1004])
    def test_turning_at_30_s(self, tmp_path, seed):
        run, result = score_zt_sdn(tmp_path, seed, 30.0)
        assert 30.0 < run.time_to_isolate_s <= 36.0
        assert result.predicted == "grayhole"
        assert result.onset_s == 30.0
        assert 0.0 < result.detection_latency_s <= 6.0

    def test_contained_by_trust_before_the_tell_can_name_it(self, tmp_path):
        """A known limit, pinned so it is reported rather than rediscovered.

        On some seeds zt_sdn's trust score collapses below the isolation line
        before the timeout-rate tell has its four samples. Quarantine then
        stops new outcomes, no ``anomaly`` event is ever recorded, and the
        scorer has nothing to name: the grayhole is contained but unlabelled.
        """
        run, result = score_zt_sdn(tmp_path, 3, 30.0)
        assert run.time_to_isolate_s is not None
        assert result.truth == "grayhole"
        assert result.predicted == "none"
        assert result.detection_latency_s is None
