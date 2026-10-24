"""The on-off attacker: on its own, in the simulator, and named by the scorer.

It lies like the Sybil for ``on_s``, is honest for ``off_s``, and repeats from
its onset. These pin the phase timing, that it is honest before ``start_s``,
that it draws nothing and leaves the paired workload alone, that its
recording validates, that the scorer names it ``onoff``, and where that stops.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import replace

import pytest

from turncoat_sdn.attacks import OnOff, Status, Sybil
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import SCENARIOS, SimConfig, as_rows, malicious_roles, scenario_attacks
from turncoat_sdn.sim import simulate as _simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = SimConfig(sim_s=60.0, n_nodes=6, onoff_on_s=5.0, onoff_off_s=5.0)
ONSET = 20.0
DELAYED = replace(SHORT, attack_start_s=ONSET)
HOOKS = {"trust": SimTrustModel, "latency_tell": latency_tell}
HONEST = Status(claimed_cpu=0.75, rtt_ms=52.5)
JITTER = 2.5


def round_robin(n, rng):
    """Keeps feeding every node, so the attacker sees traffic all run."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def simulate(scenario, seed=3, config=SHORT, **kwargs):
    return _simulate(round_robin, scenario, seed, config=config, **HOOKS, **kwargs)


def record(tmp_path, scenario="onoff", seed=3, config=DELAYED, **kwargs):
    path = tmp_path / "run.jsonl"
    with EventWriter(path, backend="sim", seed=seed, strategy="rr", scenario=scenario) as rec:
        run = simulate(scenario, seed, config, recorder=rec, **kwargs)
    return run, read_events(path), path


def of_type(events, event_type, node=None):
    return [
        ev for ev in events if ev["type"] == event_type and (node is None or ev["node"] == node)
    ]


class TestProfile:
    def test_label_and_defaults(self):
        attack = OnOff()
        assert attack.name == "onoff"
        assert (attack.start_s, attack.on_s, attack.off_s) == (0.0, 10.0, 10.0)
        assert (attack.claimed_cpu, attack.slowdown, attack.rtt_ms) == (0.1, 2.0, 220.0)
        assert attack.ground_truth() == {"attack": "onoff", "attack_start_s": 0.0}

    @pytest.mark.parametrize("field", ["on_s", "off_s"])
    @pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf"), "5"])
    def test_rejects_a_bad_phase_length(self, field, bad):
        with pytest.raises(ValueError, match=field):
            OnOff(**{field: bad})

    def test_keeps_the_sybils_validation(self):
        with pytest.raises(ValueError, match="slowdown"):
            OnOff(slowdown=0)

    @pytest.mark.parametrize(
        ("now", "hostile"),
        [
            (0.0, False),
            (9.999, False),  # before the onset
            (10.0, True),  # first hostile phase: [10, 14)
            (13.999, True),
            (14.0, False),  # first honest phase: [14, 20)
            (19.999, False),
            (20.0, True),  # and again, every 10 s
            (23.5, True),
            (24.0, False),
            (104.0, False),
            (110.0, True),
        ],
    )
    def test_phase_timing(self, now, hostile):
        assert OnOff(start_s=10.0, on_s=4.0, off_s=6.0).hostile(now) is hostile

    def test_lies_like_a_sybil_while_hostile(self):
        attack, sybil = OnOff(on_s=5.0, off_s=5.0), Sybil()
        rng = random.Random(0)
        assert attack.service_time(2.0, 0.2, rng) == sybil.service_time(2.0, 0.2, rng)
        assert attack.status(2.0, HONEST, JITTER, rng) == sybil.status(2.0, HONEST, JITTER, rng)
        assert attack.status(2.0, HONEST, JITTER, rng) == Status(0.1, 222.5)

    def test_honest_between_hostile_phases_and_before_onset(self):
        attack = OnOff(start_s=10.0, on_s=5.0, off_s=5.0)
        rng = random.Random(0)
        for now in (3.0, 16.0, 29.0):
            assert attack.service_time(now, 0.2, rng) == 0.2
            assert attack.status(now, HONEST, JITTER, rng) == HONEST

    def test_draws_nothing(self):
        rng = random.Random(0)
        state = rng.getstate()
        attack = OnOff(on_s=1.0, off_s=1.0)
        for now in (0.5, 1.5, 2.5):
            attack.service_time(now, 0.2, rng)
            attack.status(now, HONEST, JITTER, rng)
        assert rng.getstate() == state

    def test_repr(self):
        assert repr(OnOff(5.0, on_s=4.0, off_s=6.0)) == (
            "OnOff(start_s=5, on_s=4, off_s=6, claimed_cpu=0.1, slowdown=2, rtt_ms=220)"
        )


class TestScenario:
    def test_is_a_built_in_scenario(self):
        assert SCENARIOS[-2:] == ("grayhole", "onoff")
        assert SCENARIOS[:4] == ("clean", "sybil", "drop", "both")  # FYP order kept

    def test_takes_its_settings_from_the_config(self):
        cfg = replace(DELAYED, onoff_on_s=7.0, onoff_off_s=3.0, sybil_rtt_ms=150.0)
        attacks = scenario_attacks("onoff", cfg)
        assert set(attacks) == {5}
        attack = attacks[5]
        assert isinstance(attack, OnOff)
        assert (attack.start_s, attack.on_s, attack.off_s) == (ONSET, 7.0, 3.0)
        assert (attack.claimed_cpu, attack.slowdown, attack.rtt_ms) == (0.1, 2.0, 150.0)
        assert malicious_roles("onoff", 8) == {7: "onoff"}

    def test_the_scenario_equals_passing_the_attack(self):
        by_name = simulate("onoff")
        by_object = simulate("clean", attacks={5: OnOff(on_s=5.0, off_s=5.0)})
        assert by_object.latencies_ms == by_name.latencies_ms
        assert as_rows([by_object])[0] == {**as_rows([by_name])[0], "scenario": "clean"}


class TestInTheSimulator:
    def test_polls_follow_the_phases(self, tmp_path):
        _, events, _ = record(tmp_path)
        attack = scenario_attacks("onoff", DELAYED)[5]
        jitter = SHORT.rtt_jitter_ms
        hostile, honest = [], []
        for ev in of_type(events, "node_status"):
            (hostile if attack.hostile(ev["ts"]) else honest).append(ev["nodes"]["srv6"])
        assert hostile and honest
        assert all(s["claimed_cpu"] == SHORT.sybil_claimed_cpu for s in hostile)
        assert all(s["rtt_ms"] >= SHORT.sybil_rtt_ms - jitter for s in hostile)
        assert all(s["rtt_ms"] <= SHORT.base_rtt_ms + jitter for s in honest)

    def test_nothing_is_flagged_before_onset(self, tmp_path):
        _, events, _ = record(tmp_path)
        flagged = of_type(events, "anomaly", "srv6")
        assert flagged, "the attacker was never flagged at all"
        assert min(ev["ts"] for ev in flagged) >= ONSET

    def test_it_is_flagged_again_after_going_quiet(self, tmp_path):
        # Flagged in more than one hostile phase, with clean polls between.
        _, events, _ = record(tmp_path)
        period = SHORT.onoff_on_s + SHORT.onoff_off_s
        phases = {int((ev["ts"] - ONSET) // period) for ev in of_type(events, "anomaly", "srv6")}
        assert len(phases) >= 3

    def test_runs_are_reproducible(self):
        first = simulate("onoff", config=DELAYED)
        second = simulate("onoff", config=DELAYED)
        assert as_rows([first]) == as_rows([second])
        assert first.latencies_ms == second.latencies_ms

    def test_it_never_shifts_the_workload(self):
        assert simulate("onoff", config=DELAYED).offered == simulate("clean").offered

    def test_the_recording_validates_and_carries_the_ground_truth(self, tmp_path):
        _, events, path = record(tmp_path)
        assert validate_file(path).ok
        nodes = {node["id"]: node for node in events[1]["graph"]["nodes"]}
        assert (nodes["srv6"]["attack"], nodes["srv6"]["attack_start_s"]) == ("onoff", ONSET)
        config = events[1]["config"]
        assert (config["onoff_on_s"], config["onoff_off_s"]) == (5.0, 5.0)


def score_zt_sdn(tmp_path, seed, onset, on_s=10.0, off_s=10.0):
    path = tmp_path / f"zt-{seed}-{onset:g}-{on_s:g}-{off_s:g}.jsonl"
    cfg = SimConfig(attack_start_s=onset, onoff_on_s=on_s, onoff_off_s=off_s)
    with EventWriter(path, backend="sim", seed=seed, scenario="onoff") as rec:
        _simulate(STRATEGIES["zt_sdn"], "onoff", seed, config=cfg, recorder=rec, **HOOKS)
    assert validate_file(path).ok
    return {r.subject: r for r in score_run(read_events(path))}["srv8"]


class TestTheScorerNamesIt:
    @pytest.mark.parametrize("onset", [0.0, 30.0])
    @pytest.mark.parametrize("seed", [1, 2, 1000, 1001])
    def test_with_the_default_phases(self, tmp_path, seed, onset):
        result = score_zt_sdn(tmp_path, seed, onset)
        assert result.truth == "onoff"
        assert result.predicted == "onoff"
        assert result.onset_s == onset
        # It can only be named once it has gone quiet and come back: one full
        # period after the onset, plus the tell's reaction time.
        assert 20.0 < result.detection_latency_s <= 25.0

    @pytest.mark.parametrize(("on_s", "off_s"), [(3.0, 3.0), (5.0, 5.0), (10.0, 3.0), (5.0, 15.0)])
    def test_across_phase_lengths(self, tmp_path, on_s, off_s):
        result = score_zt_sdn(tmp_path, 1, 0.0, on_s, off_s)
        assert result.predicted == "onoff"
        # Within two periods: short hostile phases take longer to trip the tell.
        assert result.detection_latency_s <= 2 * (on_s + off_s) + 5.0

    def test_an_honest_phase_under_3_s_is_labelled_sybil(self, tmp_path):
        """A known limit, pinned so it is reported rather than rediscovered:
        the classifier needs three clean polls to see the attacker go quiet."""
        result = score_zt_sdn(tmp_path, 1, 0.0, 10.0, 2.0)
        assert result.predicted == "sybil"
        assert result.family_correct

    def test_phases_under_3_s_are_never_flagged(self, tmp_path):
        """A known limit: toggling every 2 s or faster, the latency tell never
        collects the consecutive strikes it needs, so nothing fires at all."""
        result = score_zt_sdn(tmp_path, 1, 0.0, 2.0, 2.0)
        assert result.predicted == "none"

    def test_long_phases_need_a_long_run(self, tmp_path):
        """A known limit: the verdict is the modal label, and every poll before
        the first resumption reads as a Sybil. A 60 s period in a 120 s run is
        named on-off only late, and outvoted."""
        result = score_zt_sdn(tmp_path, 1, 0.0, 30.0, 30.0)
        assert result.predicted == "sybil"
        assert result.first_correct_t is not None
