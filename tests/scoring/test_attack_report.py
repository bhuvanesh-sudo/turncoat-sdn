"""The attack report, moved from ``evaluation/attack_report.py``.

Most of these are the final-year project's ``tests/test_attack_report.py``,
with the import paths changed and unittest assertions written as plain
asserts. They build small hand-written recordings, so each rule is exercised in
isolation.

Tests that need the live stack stay behind: the pins against the real
authenticator constants, the controller's ``topology_graph()``, the shipped
YAML configs and the real ``EventBus``. They move with the Mininet backend.

``TestSimulatedRun`` is new. It scores a recording of a real simulator run
(see ``conftest.py``), which is this task's "done when".
"""

from __future__ import annotations

import json

import pytest

from turncoat_sdn.scoring.attack_classifier import (
    ATTACK_BLACKHOLE,
    ATTACK_FLOOD,
    ATTACK_ONOFF,
    ATTACK_SPOOF,
    ATTACK_SYBIL,
    NO_ATTACK,
    SIG_LATENCY_TELL,
    SIG_PACKET_DROP,
)
from turncoat_sdn.scoring.attack_report import (
    AUTH_KIND_BAD_RESPONSE,
    AUTH_KIND_IP_PIN,
    SubjectResult,
    client_observations,
    confusion_matrix,
    format_report,
    ground_truth,
    main,
    node_cycles,
    onset_times,
    per_class_metrics,
    score_run,
    subject_aliases,
    write_csv,
)

T0 = 1000.0


def topology_event(servers, iots=()):
    nodes = [
        {"id": n, "kind": "server", "ip": f"10.0.1.{i + 1}", "attack": a, "attack_start_s": s}
        for i, (n, a, s) in enumerate(servers)
    ]
    nodes += [
        {"id": n, "kind": "iot", "ip": f"10.0.2.{i + 1}", "attack": a, "attack_start_s": s}
        for i, (n, a, s) in enumerate(iots)
    ]
    return {"ts": T0, "type": "topology", "graph": {"nodes": nodes, "links": []}}


def anomaly(t, node, signals):
    return {"ts": t, "type": "anomaly", "node": node, "reasons": ["tell"], "signals": signals}


def heartbeat(t):
    return {"ts": t, "type": "node_status", "nodes": {}}


class TestGroundTruth:
    def test_reads_servers_and_iot_devices(self):
        events = [
            topology_event(
                [("srv1", "sybil", 10.0), ("srv2", "none", 0.0)],
                [("iot1", "flood", 5.0)],
            )
        ]
        truth = ground_truth(events)
        assert truth["srv1"] == ("node", ATTACK_SYBIL)
        assert truth["srv2"] == ("node", NO_ATTACK)
        assert truth["iot1"] == ("client", ATTACK_FLOOD)

    def test_legacy_drop_maps_to_standard_blackhole_terminology(self):
        events = [topology_event([("srv1", "drop", 0.0)])]
        assert ground_truth(events)["srv1"] == ("node", ATTACK_BLACKHOLE)

    def test_onsets_and_aliases(self):
        events = [topology_event([("srv1", "sybil", 12.5)], [("iot1", "flood", 3.0)])]
        assert onset_times(events)["srv1"] == 12.5
        assert subject_aliases(events) == {"10.0.2.1": "iot1"}

    def test_no_topology_event_yields_no_ground_truth(self):
        assert ground_truth([{"ts": T0, "type": "route"}]) == {}


class TestCycleReconstruction:
    def test_node_status_supplies_the_clean_cycles(self):
        events = [
            anomaly(T0 + 0.1, "srv1", {SIG_LATENCY_TELL: 6.0}),
            heartbeat(T0 + 0.5),
            heartbeat(T0 + 1.5),
            heartbeat(T0 + 2.5),
        ]
        windows = node_cycles(events, ["srv1"])
        assert len(windows["srv1"]) == 3
        assert windows["srv1"][0].signals
        # Cycles 2 and 3 had no anomaly: recorded as CLEAN, not skipped. The
        # on-off rule is entirely dependent on these existing.
        assert windows["srv1"][1].signals == {}
        assert windows["srv1"][2].signals == {}

    def test_signals_do_not_leak_across_cycles(self):
        events = [
            anomaly(T0, "srv1", {SIG_PACKET_DROP: 1.0}),
            heartbeat(T0 + 0.5),
            heartbeat(T0 + 1.5),
        ]
        assert node_cycles(events, ["srv1"])["srv1"][1].signals == {}

    def test_anomaly_without_signals_counts_as_flagged_not_clean(self):
        # A detection must never be silently downgraded to a clean cycle.
        events = [
            {"ts": T0, "type": "anomaly", "node": "srv1", "reasons": ["prose only"]},
            heartbeat(T0 + 0.5),
        ]
        assert node_cycles(events, ["srv1"])["srv1"][0].signals

    def test_client_observations_split_by_signal_kind(self):
        events = [
            {"ts": T0, "type": "flood", "client_ip": "10.0.2.1", "ratio": 40.0},
            {
                "ts": T0 + 1,
                "type": "auth_denied",
                "device_id": "iot2",
                "source_ip": "10.0.2.2",
                "kind": AUTH_KIND_IP_PIN,
            },
            {
                "ts": T0 + 2,
                "type": "auth_denied",
                "device_id": "iot3",
                "source_ip": "10.0.2.3",
                "kind": AUTH_KIND_BAD_RESPONSE,
            },
        ]
        obs = client_observations(events)
        # Keyed by the SOURCE IP: the host that acted. For a spoofer that is
        # the only field naming the attacker at all -- device_id names its
        # victim.
        assert {"10.0.2.1", "10.0.2.2", "10.0.2.3"} <= set(obs)


def _build_recording():
    """A short run with one of each node-side attack plus honest nodes."""
    events = [
        topology_event(
            [("srv1", "sybil", 5.0), ("srv2", "drop", 5.0), ("srv3", "none", 0.0)],
            [("iot1", "flood", 5.0), ("iot2", "spoof", 2.0), ("iot3", "none", 0.0)],
        )
    ]
    # iot2 is the SPOOFER here: it sends from its own address (10.0.2.2)
    # while claiming to be iot1. The denial must be filed against iot2.
    events.append(
        {
            "ts": T0 + 2.2,
            "type": "auth_denied",
            "device_id": "iot1",
            "source_ip": "10.0.2.2",
            "kind": AUTH_KIND_IP_PIN,
            "reason": "iot1 is pinned to another IP",
        }
    )
    events.append(
        {"ts": T0 + 6.0, "type": "flood", "client_ip": "10.0.2.1", "ratio": 40.0, "rate_hz": 40.0}
    )
    for c in range(40):
        t = T0 + c
        if c >= 5:
            events.append(anomaly(t, "srv1", {SIG_LATENCY_TELL: 6.0}))
            events.append(anomaly(t, "srv2", {SIG_PACKET_DROP: 1.0}))
        events.append(heartbeat(t + 0.5))
    return events


def _onoff_recording(pattern):
    events = [topology_event([("srv1", "onoff", 0.0)])]
    for c, bad in enumerate(pattern):
        t = T0 + c
        if bad:
            events.append(anomaly(t, "srv1", {SIG_LATENCY_TELL: 6.0}))
        events.append(heartbeat(t + 0.5))
    return events


class TestScoreRun:
    @pytest.fixture
    def results(self):
        return {r.subject: r for r in score_run(_build_recording())}

    def test_every_configured_subject_is_scored(self, results):
        assert set(results) == {"srv1", "srv2", "srv3", "iot1", "iot2", "iot3"}

    def test_node_attacks_are_classified_correctly(self, results):
        assert results["srv1"].predicted == ATTACK_SYBIL
        assert results["srv2"].predicted == ATTACK_BLACKHOLE

    def test_client_attacks_are_classified_correctly(self, results):
        # iot1's evidence arrives keyed by IP and must be folded onto its
        # device id, or it would score as an unseen subject.
        assert results["iot1"].predicted == ATTACK_FLOOD
        assert results["iot2"].predicted == ATTACK_SPOOF

    def test_honest_subjects_are_not_accused(self, results):
        assert results["srv3"].predicted == NO_ATTACK
        assert results["iot3"].predicted == NO_ATTACK
        assert results["srv3"].correct

    def test_detection_latency_is_measured_from_configured_onset(self, results):
        r = results["srv1"]
        assert r.onset_s == 5.0
        # Flagged from cycle 5, closed by the node_status at +5.5s, against a
        # 5.0s onset.
        assert r.detection_latency_s == pytest.approx(0.5, abs=1e-3)

    def test_latency_is_unknown_rather_than_guessed_without_onset_truth(self):
        events = _build_recording()
        for node in events[0]["graph"]["nodes"]:
            node.pop("attack_start_s", None)
        results = {r.subject: r for r in score_run(events)}
        assert results["srv1"].detection_latency_s is None

    def test_run_verdict_is_modal_not_final(self):
        # An on-off attacker is correctly abstained on during a good phase, so
        # the label standing at the end of a recording says more about where
        # the run was cut than about what the system concluded. The window is
        # wide enough to span a full 12-cycle period but narrower than the
        # 40-cycle clean tail, so the classifier really does abstain at the end.
        events = _onoff_recording(([True] * 6 + [False] * 6) * 4 + [False] * 40)
        result = score_run(events, window_cycles=30)[0]
        assert result.abstained_cycles > 0, "the tail should abstain, or this proves nothing"
        assert result.predicted == ATTACK_ONOFF


class TestOnOffWindowConstraint:
    """A window narrower than one on-off period degrades to a sybil verdict.

    Not a defect: with only one phase in view at a time the evidence genuinely
    looks like sustained misbehaviour, and the attacker is still caught either
    way -- only the LABEL degrades. Pinned because it is why
    DEFAULT_WINDOW_CYCLES is set where it is.
    """

    PERIOD = 12  # 6 bad + 6 clean cycles

    def _predicted(self, window_cycles):
        events = _onoff_recording(([True] * 6 + [False] * 6) * 6)
        return score_run(events, window_cycles=window_cycles)[0].predicted

    def test_window_spanning_the_period_recovers_onoff(self):
        assert self._predicted(self.PERIOD * 2) == ATTACK_ONOFF

    def test_window_narrower_than_the_period_reads_as_sybil(self):
        assert self._predicted(self.PERIOD - 2) == ATTACK_SYBIL


class TestMatrixAndMetrics:
    @pytest.fixture
    def results(self):
        return score_run(_build_recording())

    def test_confusion_matrix_is_all_diagonal_when_every_call_is_right(self, results):
        for truth, row in confusion_matrix(results).items():
            expected = sum(1 for r in results if r.truth == truth)
            assert row[truth] == expected, truth
            assert sum(c for p, c in row.items() if p != truth) == 0, truth

    def test_per_class_metrics_include_the_none_class(self, results):
        # NO_ATTACK is scored like any other class: it is the class that
        # catches false accusations of honest nodes.
        metrics = per_class_metrics(results)
        assert metrics[NO_ATTACK]["support"] == 2.0

    def test_a_misclassification_shows_up_off_diagonal(self):
        results = [
            SubjectResult("srv1", "node", ATTACK_SYBIL, ATTACK_BLACKHOLE),
            SubjectResult("srv2", "node", ATTACK_BLACKHOLE, ATTACK_BLACKHOLE),
        ]
        matrix = confusion_matrix(results)
        assert matrix[ATTACK_SYBIL][ATTACK_BLACKHOLE] == 1
        assert matrix[ATTACK_SYBIL][ATTACK_SYBIL] == 0

        metrics = per_class_metrics(results)
        # sybil was never predicted: recall 0 on a support of 1.
        assert metrics[ATTACK_SYBIL]["recall"] == 0.0
        # blackhole was predicted twice and right once: precision 0.5.
        assert metrics[ATTACK_BLACKHOLE]["precision"] == 0.5
        assert metrics[ATTACK_BLACKHOLE]["recall"] == 1.0

    def test_report_renders(self, results):
        text = format_report(results)
        assert "CONFUSION MATRIX" in text
        assert "Overall accuracy" in text
        assert "UPPER BOUND" in text
        assert "Honest subjects wrongly labelled" in text

    def test_csv_round_trips(self, results, tmp_path):
        path = tmp_path / "out.csv"
        write_csv(results, str(path))
        rows = path.read_text("utf-8").strip().splitlines()
        assert len(rows) == len(results) + 1
        assert "detection_latency_s" in rows[0]


class TestCli:
    def test_main_scores_a_recording_on_disk(self, tmp_path, capsys):
        path = tmp_path / "events.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in _build_recording()), "utf-8")
        assert main([str(path)]) == 0
        assert "CONFUSION MATRIX" in capsys.readouterr().out

    def test_main_skips_a_truncated_tail_line(self, tmp_path):
        path = tmp_path / "events.jsonl"
        lines = [json.dumps(e) for e in _build_recording()]
        path.write_text("\n".join(lines) + '\n{"ts": 10', "utf-8")
        assert main([str(path)]) == 0

    def test_main_refuses_a_recording_with_no_ground_truth(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text(json.dumps({"ts": T0, "type": "route"}) + "\n", "utf-8")
        assert main([str(path)]) == 1

    def test_main_refuses_an_empty_recording(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text("", "utf-8")
        assert main([str(path)]) == 1


class TestSpoofIsBlamedOnTheAttackerNotTheVictim:
    """A spoofer impersonated another device. The source-IP pin refused it,
    but filing the denial under the CLAIMED device_id would label the victim
    and leave the attacker clean -- a false accusation made out of a
    successful defence."""

    @pytest.fixture
    def results(self):
        events = [
            topology_event(
                [("srv1", "none", 0.0)],
                [("iot1", "none", 0.0), ("iot2", "spoof", 2.0)],
            ),
            # iot2 (at 10.0.2.2) presents a correct response for iot1.
            {
                "ts": T0 + 3.0,
                "type": "auth_denied",
                "device_id": "iot1",
                "source_ip": "10.0.2.2",
                "kind": AUTH_KIND_IP_PIN,
                "reason": "iot1 is pinned to 10.0.2.1",
            },
        ]
        return {r.subject: r for r in score_run(events)}

    def test_the_spoofer_is_labelled(self, results):
        assert results["iot2"].predicted == ATTACK_SPOOF
        assert results["iot2"].correct

    def test_the_victim_is_not_labelled(self, results):
        assert results["iot1"].predicted == NO_ATTACK
        assert results["iot1"].correct


class TestSimulatedRun:
    """Score a recording of a real simulator run, end to end."""

    def test_both_attackers_are_classified_with_a_latency(self, simulated_recording):
        events, run = simulated_recording("both", 1000)
        results = {r.subject: r for r in score_run(events)}

        assert results["srv8"].truth == ATTACK_SYBIL
        assert results["srv8"].predicted == ATTACK_SYBIL
        assert results["srv7"].truth == ATTACK_BLACKHOLE  # the simulator's "drop"
        assert results["srv7"].predicted == ATTACK_BLACKHOLE
        assert all(results[f"srv{i}"].predicted == NO_ATTACK for i in range(1, 7))

        # Both are named on the poll at which the simulator isolated them.
        assert results["srv8"].detection_latency_s == run.time_to_isolate_s == 3.0
        assert results["srv7"].detection_latency_s == 3.0

    def test_the_report_prints_a_matrix_and_a_latency(self, simulated_recording, capsys):
        events, _ = simulated_recording("both", 1000)
        print(format_report(score_run(events)))
        out = capsys.readouterr().out
        assert "CONFUSION MATRIX" in out
        assert "Detection latency: mean 3.0s, max 3.0s" in out
        assert "Overall accuracy: 8/8 = 100.0%" in out

    @pytest.mark.parametrize("scenario", ["sybil", "drop"])
    @pytest.mark.parametrize("seed", [1000, 1001, 1002])
    def test_single_attacker_scenarios_score_cleanly(self, simulated_recording, scenario, seed):
        events, _ = simulated_recording(scenario, seed)
        results = score_run(events)
        assert all(r.correct for r in results)
        attackers = [r for r in results if r.truth != NO_ATTACK]
        assert len(attackers) == 1
        assert attackers[0].detection_latency_s is not None

    def test_a_clean_run_accuses_nobody(self, simulated_recording):
        events, _ = simulated_recording("clean", 1000)
        results = score_run(events)
        assert {r.predicted for r in results} == {NO_ATTACK}
        assert all(r.abstained_cycles == r.total_cycles for r in results)
