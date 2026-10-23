"""Recording a run to ``events.jsonl``.

The v0.2 promise: every simulated run produces a file that passes the
validator, and recording it changes nothing about the run. The recording is
written by the simulator through its ``recorder`` hook into arj's
``EventWriter``; these tests read it back the way a scorer would.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_classifier import SIG_LATENCY_TELL, SIG_PACKET_DROP
from turncoat_sdn.sim import (
    SCENARIOS,
    SimConfig,
    as_rows,
    malicious_roles,
    node_id,
    run_paired,
    simulate,
)
from turncoat_sdn.sim.engine import DENIED_REASON, SIGNAL_LATENCY_TELL, SIGNAL_PACKET_DROP
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = SimConfig(sim_s=25.0, n_nodes=6)


def record(path, router, scenario, seed, *, config=SHORT, **hooks):
    """Run once into ``path`` and return the run and the events read back."""
    with EventWriter(
        path, backend="sim", seed=seed, strategy=router.__name__, scenario=scenario
    ) as rec:
        run = simulate(router, scenario, seed, config=config, recorder=rec, **hooks)
    return run, read_events(path)


def of_type(events, event_type):
    return [ev for ev in events if ev["type"] == event_type]


class TestValidRecording:
    """Every simulated run produces a file that passes the validator."""

    @pytest.mark.parametrize("scenario", SCENARIOS)
    @pytest.mark.parametrize("hooked", [False, True], ids=["blind", "trust_and_tell"])
    def test_every_scenario_validates(self, routers, tmp_path, scenario, hooked):
        hooks = {"trust": SimTrustModel, "latency_tell": latency_tell} if hooked else {}
        path = tmp_path / "run.jsonl"
        record(path, routers["least_conn"], scenario, 1000, **hooks)

        report = validate_file(path)
        assert report.ok, report.format(str(path))

    def test_header_then_topology_with_ground_truth(self, routers, tmp_path):
        _, events = record(tmp_path / "run.jsonl", routers["round_robin"], "both", 7)

        header, topology = events[0], events[1]
        assert header["type"] == "header"
        assert (header["backend"], header["seed"], header["scenario"]) == ("sim", 7, "both")
        assert topology["type"] == "topology" and topology["ts"] == 0.0

        nodes = {node["id"]: node for node in topology["graph"]["nodes"]}
        assert list(nodes) == [node_id(i) for i in range(SHORT.n_nodes)]
        roles = malicious_roles("both", SHORT.n_nodes)
        for i in range(SHORT.n_nodes):
            node = nodes[node_id(i)]
            assert node["attack"] == roles.get(i, "none")
            # Attackers are hostile from the first second; honest nodes have no onset.
            assert node.get("attack_start_s") == (0.0 if i in roles else None)
        assert topology["config"]["n_nodes"] == SHORT.n_nodes

    def test_signal_names_match_the_attack_classifier(self):
        assert SIGNAL_LATENCY_TELL == SIG_LATENCY_TELL
        assert SIGNAL_PACKET_DROP == SIG_PACKET_DROP


class TestRecordingChangesNothing:
    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_recorded_and_unrecorded_runs_match(self, routers, tmp_path, scenario):
        hooks = {"trust": SimTrustModel, "latency_tell": latency_tell}
        for name, router in routers.items():
            plain = simulate(router, scenario, 1001, config=SHORT, **hooks)
            recorded, _ = record(tmp_path / f"{name}.jsonl", router, scenario, 1001, **hooks)
            assert as_rows([recorded]) == as_rows([plain])
            assert recorded.latencies_ms == plain.latencies_ms


class TestRecordingAgreesWithTheRun:
    """The file holds the same run the metrics describe."""

    @pytest.mark.parametrize("scenario", ["clean", "drop", "both"])
    def test_routes_and_reports_add_up(self, routers, tmp_path, scenario):
        run, events = record(tmp_path / "run.jsonl", routers["random"], scenario, 1002)
        routes = of_type(events, "route")
        reports = of_type(events, "report")
        statuses = Counter(r["status"] for r in reports)

        assert len(routes) + len(of_type(events, "route_denied")) == run.offered
        assert statuses["success"] == run.completed
        assert statuses["timeout"] == run.failed
        assert Counter(r["chosen"] for r in routes) == {
            node_id(i): count for i, count in enumerate(run.served) if count
        }
        latencies = [r["latency_ms"] for r in reports if r["status"] == "success"]
        assert latencies == [round(x, 3) for x in run.latencies_ms]

    def test_every_report_names_the_node_its_task_was_routed_to(self, routers, tmp_path):
        _, events = record(tmp_path / "run.jsonl", routers["least_conn"], "both", 1003)
        routed = {r["task"]: r["chosen"] for r in of_type(events, "route")}
        reports = of_type(events, "report")
        assert reports
        assert all(routed[r["task"]] == r["node"] for r in reports)
        assert len({r["task"] for r in reports}) == len(reports)  # one outcome per task

    def test_one_node_status_per_poll(self, routers, tmp_path):
        _, events = record(tmp_path / "run.jsonl", routers["round_robin"], "clean", 1)
        polls = of_type(events, "node_status")
        assert [p["ts"] for p in polls] == [float(t) for t in range(1, int(SHORT.sim_s) + 1)]
        assert set(polls[0]["nodes"]) == {node_id(i) for i in range(SHORT.n_nodes)}

    def test_a_clean_run_has_no_anomaly_and_no_quarantine(self, routers, tmp_path):
        _, events = record(
            tmp_path / "run.jsonl",
            routers["round_robin"],
            "clean",
            1,
            trust=SimTrustModel,
            latency_tell=latency_tell,
        )
        assert not of_type(events, "anomaly")
        assert not of_type(events, "quarantine")

    def test_quarantine_marks_the_moment_of_isolation(self, routers, tmp_path):
        run, events = record(
            tmp_path / "run.jsonl",
            routers["round_robin"],
            "both",
            1000,
            trust=SimTrustModel,
            latency_tell=latency_tell,
        )
        quarantined = {}
        for ev in of_type(events, "quarantine"):
            quarantined.setdefault(ev["node"], ev["ts"])
        attackers = {node_id(i) for i in malicious_roles("both", SHORT.n_nodes)}

        assert set(quarantined) == attackers
        assert run.time_to_isolate_s == max(quarantined.values())

    def test_anomaly_events_carry_the_signal_that_fired(self, routers, tmp_path):
        _, events = record(
            tmp_path / "run.jsonl",
            routers["round_robin"],
            "both",
            1000,
            trust=SimTrustModel,
            latency_tell=latency_tell,
        )
        signals = {}
        for ev in of_type(events, "anomaly"):
            signals.setdefault(ev["node"], set()).update(ev["signals"])
        sybil, dropper = SHORT.n_nodes, SHORT.n_nodes - 1
        assert SIGNAL_LATENCY_TELL in signals[f"srv{sybil}"]
        assert SIGNAL_PACKET_DROP in signals[f"srv{dropper}"]

    def test_a_refused_task_is_recorded_as_denied(self, tmp_path):
        def refuse_all(n, rng):
            class Refuse:
                def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                    return None

            return Refuse()

        run, events = record(tmp_path / "run.jsonl", refuse_all, "clean", 3)
        denied = of_type(events, "route_denied")
        assert len(denied) == run.offered == run.failed
        assert {d["reason"] for d in denied} == {DENIED_REASON}
        assert validate_file(tmp_path / "run.jsonl").ok


class TestPairedRecording:
    def test_one_closed_valid_file_per_run(self, routers, tmp_path):
        opened = []

        def recorders(strategy, scenario, seed):
            writer = EventWriter(
                tmp_path / f"{strategy}-{scenario}-{seed}.jsonl",
                backend="sim",
                seed=seed,
                strategy=strategy,
                scenario=scenario,
            )
            opened.append(writer)
            return writer

        config = replace(SHORT, sim_s=10.0)
        results = run_paired(
            routers, seeds=[1, 2], scenarios=["drop"], config=config, recorders=recorders
        )

        assert len(opened) == len(results) == 6
        for writer, result in zip(opened, results, strict=True):
            with pytest.raises(ValueError, match="already closed"):
                writer.write("node_status", 99.0, nodes={})
            assert validate_file(writer.path).ok
            assert writer.header["strategy"] == result.strategy
            assert writer.header["seed"] == result.seed
