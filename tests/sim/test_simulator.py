"""Behaviour of the simulator: pairing, attackers, queueing, hooks and output.

Ported from the final-year project's ``tests/test_baseline.py`` (E-01 to E-07,
E-12 and the runner tests). The detection tests that need the real ``zt_sdn``
selector and trust calculator (E-08 to E-11) move with those components.
All runs are short so the suite stays fast.
"""

from __future__ import annotations

import csv
from dataclasses import replace

import pytest

from turncoat_sdn.sim import (
    CSV_FIELDS,
    SCENARIOS,
    UNTRUSTED_DEFAULT,
    RunResult,
    SimConfig,
    as_rows,
    gini,
    malicious_roles,
    run_paired,
    simulate,
    write_csv,
)

SHORT = SimConfig(sim_s=25.0, n_nodes=6)


class TestWorkloadPairing:
    """E-01 to E-03: the property the statistics depend on."""

    def test_e01_same_seed_gives_identical_workload(self, routers):
        offered = {
            name: simulate(router, "clean", 7, config=SHORT).offered
            for name, router in routers.items()
        }
        assert len(set(offered.values())) == 1, f"workload drifted per strategy: {offered}"

    def test_e02_runs_are_reproducible(self, routers):
        first = simulate(routers["least_conn"], "both", 11, config=SHORT)
        second = simulate(routers["least_conn"], "both", 11, config=SHORT)
        assert first == second

    def test_e03_different_seeds_give_different_runs(self, routers):
        rates = {
            simulate(routers["round_robin"], "clean", s, config=SHORT).slo_violation_rate
            for s in range(20, 26)
        }
        assert len(rates) > 1, "every seed produced an identical run"


class TestAttackers:
    """E-04 to E-07: the scenarios have to actually be adversarial."""

    def test_e04_clean_scenario_has_no_attacker(self, routers):
        run = simulate(routers["round_robin"], "clean", 3, config=SHORT)
        assert run.malicious_tasks == 0
        assert run.time_to_isolate_s is None
        assert run.failed == 0, "healthy fleet should not fail tasks at 40% load"

    def test_e05_dropper_causes_failures_for_blind_baselines(self, routers):
        run = simulate(routers["round_robin"], "drop", 3, config=SHORT)
        assert run.failed > 0, "the dropper never actually dropped anything"
        assert run.malicious_share > 0.10

    def test_e06_sybil_attracts_least_connections(self, routers):
        """Claiming to be idle has to win traffic, or the attack means nothing."""
        run = simulate(routers["least_conn"], "sybil", 5, config=SHORT)
        fair_share = 1.0 / SHORT.n_nodes
        assert run.malicious_share > fair_share

    def test_e07_sybil_completes_tasks_so_trust_alone_cannot_catch_it(self, routers):
        """The Sybil is only slow. If it failed tasks, the attack would be too easy."""
        run = simulate(routers["round_robin"], "sybil", 5, config=SHORT)
        assert run.failed == 0
        assert run.mean_latency_ms > 0

    def test_attackers_sit_at_the_end_of_the_index_range(self):
        assert malicious_roles("clean", 8) == {}
        assert malicious_roles("sybil", 8) == {7: "sybil"}
        assert malicious_roles("drop", 8) == {7: "drop"}
        assert malicious_roles("both", 8) == {7: "sybil", 6: "drop"}


class TestMetrics:
    """E-12 and queueing: the numbers have to mean what the report says."""

    def test_e12_metric_arithmetic_is_consistent(self, routers):
        run = simulate(routers["random"], "both", 13, config=SHORT)
        assert run.offered > 0
        assert 0.0 <= run.slo_violation_rate <= 1.0
        # Every failure misses the deadline, so failures are a subset of violations.
        assert run.failure_rate <= run.slo_violation_rate
        assert run.completed + run.failed <= run.offered
        assert sum(run.served) <= run.offered
        assert run.p95_latency_ms >= run.mean_latency_ms

    def test_queueing_is_modelled(self, routers):
        """Latency must exceed pure service time, or routing cannot matter."""
        cfg = SimConfig(sim_s=25.0, n_nodes=2, load_factor=0.95)
        run = simulate(routers["round_robin"], "clean", 2, config=cfg)
        assert run.mean_latency_ms > cfg.service_mean_s * 1000.0

    def test_gini(self):
        assert gini([5, 5, 5, 5]) == 0.0
        assert gini([0, 0, 0]) == 0.0
        assert gini([0, 0, 0, 12]) == pytest.approx(0.75)

    def test_unknown_scenario_is_rejected(self, routers):
        with pytest.raises(ValueError, match="unknown scenario"):
            simulate(routers["random"], "nope", 1, config=SHORT)

    def test_refused_task_counts_as_failure_and_violation(self):
        def refuse_all(n, rng):
            class Refuse:
                def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                    return None

            return Refuse()

        run = simulate(refuse_all, "clean", 1, config=SHORT)
        assert run.offered > 0
        assert run.failed == run.slo_violations == run.offered
        assert sum(run.served) == 0


class TestHooks:
    """The trust model and latency tell are called the way the controller calls them."""

    def test_without_hooks_trust_is_constant(self, routers):
        seen = []

        def spy(n, rng):
            class Spy:
                def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                    seen.append(tuple(trust))
                    return 0

            return Spy()

        simulate(spy, "drop", 1, config=replace(SHORT, sim_s=3.0))
        assert seen and all(t == (UNTRUSTED_DEFAULT,) * SHORT.n_nodes for t in seen)

    def test_timeout_tell_alone_isolates_the_dropper(self, routers):
        run = simulate(routers["round_robin"], "drop", 3, config=SHORT)
        assert run.time_to_isolate_s is not None
        assert run.time_to_isolate_s <= 10.0

    def test_sybil_is_never_isolated_without_a_latency_tell(self, routers):
        run = simulate(routers["round_robin"], "sybil", 5, config=SHORT)
        assert run.time_to_isolate_s is None

    def test_trust_model_receives_every_outcome(self, routers):
        outcomes = []

        class Recorder:
            initial_score = 0.5

            def update(self, outcome):
                outcomes.append(outcome)
                return 0.9

        run = simulate(routers["round_robin"], "drop", 3, config=SHORT, trust=Recorder)
        timeouts = [o for o in outcomes if o.task_status == "timeout"]
        assert len(outcomes) == run.completed + len(timeouts)
        dropper = SHORT.n_nodes - 1
        assert timeouts and {o.node for o in timeouts} == {dropper}
        assert {o.edge_node_id for o in timeouts} == {f"srv{dropper + 1}"}
        assert all(0.0 <= o.cpu_usage <= 1.0 for o in outcomes)
        assert all(o.latency_ms >= 0.0 for o in outcomes)

    def test_low_trust_counts_as_isolated(self, routers):
        class Harsh:
            initial_score = 0.5

            def update(self, outcome):
                return 0.0 if outcome.task_status == "timeout" else 1.0

        run = simulate(routers["round_robin"], "drop", 3, config=SHORT, trust=Harsh)
        assert run.time_to_isolate_s is not None

    def test_latency_tell_is_consulted_every_poll_and_isolates_the_sybil(self, routers):
        calls = []

        class Tell:
            @staticmethod
            def fleet_latency_baseline(rtts):
                return sorted(rtts)[len(rtts) // 2]

            @staticmethod
            def evaluate_latency_tell(claimed_cpu, measured_rtt_ms, fleet_baseline_ms, strikes):
                calls.append(strikes)
                slow = measured_rtt_ms > 3 * fleet_baseline_ms and claimed_cpu <= 0.25
                strikes = min(strikes + 1, 4) if slow else max(strikes - 1, 0)

                class Result:
                    pass

                result = Result()
                result.tripped, result.strikes = strikes >= 3, strikes
                return result

        cfg = replace(SHORT, sim_s=10.0)
        run = simulate(routers["round_robin"], "sybil", 5, config=cfg, latency_tell=Tell)
        polls = int(cfg.sim_s / cfg.poll_s)
        assert len(calls) == polls * cfg.n_nodes
        assert run.time_to_isolate_s == pytest.approx(3.0)


class TestPairedRuns:
    """The runner and its CSV output."""

    def test_shape_order_and_pairing(self, routers):
        strategies = {k: routers[k] for k in ("round_robin", "least_conn")}
        cfg = SimConfig(sim_s=15.0, n_nodes=4)
        results = run_paired(strategies, seeds=[1, 2], scenarios=("clean", "drop"), config=cfg)
        assert [(r.scenario, r.seed, r.strategy) for r in results] == [
            (sc, seed, st)
            for sc in ("clean", "drop")
            for seed in (1, 2)
            for st in ("round_robin", "least_conn")
        ]
        offered = {(r.scenario, r.seed): set() for r in results}
        for r in results:
            offered[(r.scenario, r.seed)].add(r.offered)
        assert all(len(v) == 1 for v in offered.values())

    def test_defaults_cover_every_scenario(self, routers):
        cfg = SimConfig(sim_s=5.0, n_nodes=4)
        results = run_paired({"random": routers["random"]}, seeds=[1], config=cfg)
        assert tuple(r.scenario for r in results) == SCENARIOS

    def test_row_keys_are_the_csv_columns_in_order(self, routers):
        run = simulate(routers["random"], "clean", 1, config=SHORT)
        assert tuple(as_rows([run])[0]) == CSV_FIELDS

    def test_a_written_csv_reads_back_as_the_same_values(self, routers, tmp_path):
        results = run_paired(
            {"random": routers["random"]},
            seeds=[1, 2],
            scenarios=("clean", "drop"),
            config=SimConfig(sim_s=15.0, n_nodes=4),
        )
        path = tmp_path / "out.csv"
        write_csv(results, path)
        with path.open(newline="", encoding="utf-8") as f:
            from_file = list(csv.DictReader(f))
        in_memory = as_rows(results)
        assert from_file == [{k: str(v) for k, v in row.items()} for row in in_memory]

    def test_a_run_that_never_isolated_stays_empty_not_zero(self):
        rows = as_rows([RunResult(strategy="x", scenario="clean", seed=1, offered=1)])
        assert rows[0]["time_to_isolate_s"] == ""
