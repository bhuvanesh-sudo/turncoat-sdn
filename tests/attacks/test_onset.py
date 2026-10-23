"""Attacks inside the simulator: the move kept every number, and onset works.

The built-in scenarios now run their Sybil and Blackhole through the attack
interface. ``tests/sim/test_golden.py``, ``tests/trust/test_zt_sdn.py`` and
``tests/cli/test_golden.py`` pin the numbers that proves unchanged; the tests
here pin the interface itself and the turncoat behaviour: honest before
``start_s``, hostile after, and the onset written into the recording.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from turncoat_sdn.attacks import Blackhole, ServerAttack, Sybil
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
    """Keeps feeding every node, so attackers see traffic all run."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def simulate(scenario, seed=3, config=SHORT, **kwargs):
    return _simulate(round_robin, scenario, seed, config=config, **HOOKS, **kwargs)


def record(tmp_path, scenario, seed=3, config=DELAYED, **kwargs):
    path = tmp_path / "run.jsonl"
    with EventWriter(path, backend="sim", seed=seed, strategy="rr", scenario=scenario) as rec:
        run = simulate(scenario, seed, config, recorder=rec, **kwargs)
    return run, read_events(path), path


def of_type(events, event_type, node=None):
    return [
        ev for ev in events if ev["type"] == event_type and (node is None or ev["node"] == node)
    ]


class TestScenariosUseTheInterface:
    def test_scenario_attacks_places_a_sybil_and_a_blackhole(self):
        attacks = scenario_attacks("both", SHORT)
        assert set(attacks) == {5, 4}
        assert isinstance(attacks[5], Sybil) and isinstance(attacks[4], Blackhole)
        assert scenario_attacks("clean", SHORT) == {}

    def test_the_sybil_takes_its_settings_from_the_config(self):
        cfg = replace(SHORT, sybil_claimed_cpu=0.2, sybil_slowdown=1.5, sybil_rtt_ms=150.0)
        sybil = scenario_attacks("sybil", cfg)[5]
        assert (sybil.claimed_cpu, sybil.slowdown, sybil.rtt_ms) == (0.2, 1.5, 150.0)

    def test_attack_start_s_delays_every_built_in_attacker(self):
        assert {a.start_s for a in scenario_attacks("both", DELAYED).values()} == {ONSET}

    def test_malicious_roles_still_names_them(self):
        assert malicious_roles("both", 8) == {7: "sybil", 6: "drop"}

    def test_unknown_scenario(self):
        with pytest.raises(ValueError, match="unknown scenario"):
            scenario_attacks("grayhole", SHORT)

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_passing_the_attacks_explicitly_changes_nothing(self, scenario):
        explicit = scenario_attacks(scenario, SHORT)
        by_name = simulate(scenario)
        by_object = simulate(scenario, attacks=explicit)
        assert as_rows([by_object]) == as_rows([by_name])
        assert by_object.latencies_ms == by_name.latencies_ms

    def test_attacks_replace_the_scenarios_attackers(self):
        # A clean scenario given a blackhole runs exactly like the drop scenario.
        given = simulate("clean", attacks={5: Blackhole()})
        drop = simulate("drop")
        assert (given.served, given.failed, given.latencies_ms) == (
            drop.served,
            drop.failed,
            drop.latencies_ms,
        )
        assert given.scenario == "clean"  # the scenario stays the run's label

    def test_an_empty_mapping_means_no_attacker(self):
        assert as_rows([simulate("both", attacks={})]) == [
            {**as_rows([simulate("clean")])[0], "scenario": "both"}
        ]

    @pytest.mark.parametrize("index", [-1, 6, True, "5"])
    def test_rejects_a_node_index_outside_the_fleet(self, index):
        with pytest.raises(ValueError, match="node index"):
            simulate("clean", attacks={index: Blackhole()})

    def test_rejects_something_that_is_not_an_attack(self):
        with pytest.raises(TypeError, match="ServerAttack"):
            simulate("clean", attacks={5: "drop"})


class TestOnsetIsRecorded:
    def test_topology_carries_each_attackers_onset(self, tmp_path):
        _, events, path = record(tmp_path, "both")
        nodes = {node["id"]: node for node in events[1]["graph"]["nodes"]}
        assert (nodes["srv6"]["attack"], nodes["srv6"]["attack_start_s"]) == ("sybil", ONSET)
        assert (nodes["srv5"]["attack"], nodes["srv5"]["attack_start_s"]) == ("drop", ONSET)
        assert all("attack_start_s" not in nodes[f"srv{i}"] for i in range(1, 5))
        assert validate_file(path).ok

    def test_each_attack_records_its_own_onset(self, tmp_path):
        attacks = {5: Sybil(start_s=7.5), 2: Blackhole(start_s=12.0)}
        _, events, path = record(tmp_path, "both", config=SHORT, attacks=attacks)
        nodes = {node["id"]: node for node in events[1]["graph"]["nodes"]}
        assert nodes["srv6"]["attack_start_s"] == 7.5
        assert nodes["srv3"]["attack_start_s"] == 12.0
        assert nodes["srv5"]["attack"] == "none"  # the scenario's dropper was replaced
        assert validate_file(path).ok

    def test_the_config_onset_is_in_the_recorded_config(self, tmp_path):
        _, events, _ = record(tmp_path, "both")
        assert events[1]["config"]["attack_start_s"] == ONSET


class TestTurncoatsAreHonestBeforeOnset:
    def test_the_blackhole_serves_until_it_turns(self, tmp_path):
        _, events, _ = record(tmp_path, "drop")
        reports = of_type(events, "report", "srv6")
        before = [r for r in reports if r["ts"] < ONSET]
        # A task accepted just before the onset may still finish just after it;
        # one client timeout later, everything it reports is a drop.
        after = [r for r in reports if r["ts"] >= ONSET + SHORT.task_timeout_s]
        assert before and all(r["status"] == "success" for r in before)
        assert after and all(r["status"] == "timeout" for r in after)

    def test_the_sybil_tells_the_truth_until_it_turns(self, tmp_path):
        _, events, _ = record(tmp_path, "sybil")
        polls = [(ev["ts"], ev["nodes"]["srv6"]) for ev in of_type(events, "node_status")]
        before = [s for t, s in polls if t < ONSET]
        after = [s for t, s in polls if t >= ONSET]
        jitter = SHORT.rtt_jitter_ms
        assert all(s["rtt_ms"] <= SHORT.base_rtt_ms + jitter for s in before)
        assert any(s["claimed_cpu"] > SHORT.sybil_claimed_cpu for s in before)
        assert all(s["claimed_cpu"] == SHORT.sybil_claimed_cpu for s in after)
        assert all(s["rtt_ms"] >= SHORT.sybil_rtt_ms - jitter for s in after)

    def test_nothing_is_flagged_before_onset(self, tmp_path):
        _, events, _ = record(tmp_path, "both")
        flagged = of_type(events, "anomaly")
        assert flagged, "the attackers were never flagged at all"
        assert min(ev["ts"] for ev in flagged) >= ONSET

    def test_isolation_comes_after_onset(self):
        run = simulate("both", config=DELAYED)
        assert run.time_to_isolate_s is not None
        assert ONSET < run.time_to_isolate_s <= ONSET + 10.0

    def test_only_traffic_after_onset_counts_as_malicious(self, tmp_path):
        run, events, _ = record(tmp_path, "both")
        routed = [ev for ev in of_type(events, "route") if ev["chosen"] in ("srv5", "srv6")]
        after = [ev for ev in routed if ev["ts"] >= ONSET]
        assert len(after) < len(routed)
        assert run.malicious_tasks == len(after)

    def test_onset_never_changes_the_workload(self):
        # Same seed, same arrivals, whatever the attackers do and whenever
        # they turn: the runs stay paired.
        offered = {simulate(s, config=c).offered for s in SCENARIOS for c in (SHORT, DELAYED)}
        assert len(offered) == 1

    def test_an_onset_after_the_run_is_a_clean_run(self):
        late = simulate("both", config=replace(SHORT, attack_start_s=SHORT.sim_s + 1))
        clean = simulate("clean")
        assert (late.served, late.failed, late.latencies_ms) == (
            clean.served,
            clean.failed,
            clean.latencies_ms,
        )
        assert late.malicious_tasks == 0
        assert late.time_to_isolate_s is None


class TestScoringFromOnset:
    def test_detection_latency_is_measured_from_onset(self, tmp_path):
        _, events, _ = record(tmp_path, "both")
        results = {r.subject: r for r in score_run(events)}
        for subject in ("srv5", "srv6"):
            r = results[subject]
            assert r.correct
            assert r.onset_s == ONSET
            assert r.detection_latency_s == pytest.approx(r.first_correct_t - ONSET)
            assert 0.0 < r.detection_latency_s <= 10.0

    def test_a_late_blackhole_is_slower_to_name_than_one_hostile_from_the_start(self, tmp_path):
        """A finding, not a defect. The timeout-rate tell reads the last ten
        outcomes, and a turncoat's window still holds its honest successes when
        it turns, so for a few polls its rate looks like a grayhole's. Named
        on the third poll when hostile from the start; later when it turns."""
        _, delayed, _ = record(tmp_path, "drop")
        from_start = tmp_path / "start"
        from_start.mkdir()
        _, at_zero, _ = record(from_start, "drop", config=SHORT)

        late = {r.subject: r for r in score_run(delayed)}["srv6"]
        early = {r.subject: r for r in score_run(at_zero)}["srv6"]
        assert late.predicted == early.predicted == "blackhole"
        assert early.detection_latency_s == 3.0
        assert late.detection_latency_s > early.detection_latency_s

    @pytest.mark.parametrize("seed", [1001, 1002, 1003, 1004])
    def test_zt_sdn_contains_a_late_blackhole_too_fast_to_name_it(self, tmp_path, seed):
        """A known result, pinned so it is reported rather than rediscovered.

        Hostile from the start, the blackhole's window is all timeouts (rate
        1.0) and it is named exactly. Turning at 30 s, the window still holds
        honest successes when the tell fires (rate 0.8, under the 0.85 bar),
        and zt_sdn quarantines it within seconds, so no outcome ever arrives to
        raise the rate. The defence works; the label falls back to the weaker
        sibling, and the FAMILY column still scores it right.
        """
        cfg = SimConfig(attack_start_s=30.0)
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="sim", seed=seed, scenario="drop") as rec:
            run = _simulate(STRATEGIES["zt_sdn"], "drop", seed, config=cfg, recorder=rec, **HOOKS)
        result = {r.subject: r for r in score_run(read_events(path))}["srv8"]

        assert run.time_to_isolate_s is not None
        assert result.truth == "blackhole"
        assert result.predicted == "grayhole"
        assert result.family_correct
        assert result.detection_latency_s is None


class CoinFlip(ServerAttack):
    """Drops half its tasks at random: an attack that draws from its rng."""

    name = "coinflip"

    def serve(self, now, demand_s, rng):
        return None if rng.random() < 0.5 else demand_s


class TestAttackRandomness:
    def test_a_random_attack_is_reproducible(self):
        first = simulate("clean", attacks={5: CoinFlip()})
        second = simulate("clean", attacks={5: CoinFlip()})
        assert as_rows([first]) == as_rows([second])
        assert first.failed > 0

    def test_its_draws_do_not_shift_the_workload(self):
        attacked = simulate("clean", attacks={5: CoinFlip()})
        clean = simulate("clean")
        assert attacked.offered == clean.offered

    def test_each_seed_gives_its_own_draws(self):
        assert simulate("clean", 3, attacks={5: CoinFlip()}).failed != (
            simulate("clean", 4, attacks={5: CoinFlip()}).failed
        )
