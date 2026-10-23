"""``turncoat score``: who was caught, how fast, and at what cost."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.run import record_run
from turncoat_sdn.cli.score import (
    DEFAULT_SLO_MS,
    recorded_slo_ms,
    routed_after,
    score_recording,
    service_totals,
)
from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.sim import SCENARIOS, SimConfig

EVENTS = Path(__file__).parent.parent / "events"
SHORT = replace(SimConfig(), sim_s=25.0)


def _record(tmp_path, strategy, scenario, seed=7):
    path = tmp_path / f"{strategy}-{scenario}.jsonl"
    run = record_run(path, strategy=strategy, scenario=scenario, seed=seed, config=SHORT)
    return path, read_events(path), run


class TestServiceTotals:
    """Rebuilt from events, the totals equal the simulator's own counts."""

    @pytest.mark.parametrize("strategy", list(STRATEGIES))
    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_counts_match_the_run(self, tmp_path, strategy, scenario):
        path, events, run = _record(tmp_path, strategy, scenario)
        assert validate_file(path).ok
        totals = service_totals(events, DEFAULT_SLO_MS)
        assert totals["offered"] == run.offered
        assert totals["completed"] == run.completed
        assert totals["failed"] == run.failed
        assert totals["slo_violations"] == run.slo_violations

    def test_latencies_match_to_the_recorded_precision(self, tmp_path):
        _, events, run = _record(tmp_path, "zt_sdn", "both")
        scores = score_recording(events)
        assert scores["service"]["mean_latency_ms"] == pytest.approx(run.mean_latency_ms, abs=1e-3)
        assert scores["service"]["p95_latency_ms"] == pytest.approx(run.p95_latency_ms, abs=1e-3)

    def test_slo_deadline_comes_from_the_recording(self, tmp_path):
        _, events, _ = _record(tmp_path, "random", "clean")
        assert recorded_slo_ms(events) == SHORT.slo_ms

    def test_tighter_deadline_means_more_violations(self, tmp_path):
        _, events, _ = _record(tmp_path, "random", "clean")
        loose = score_recording(events)["service"]["slo_violation_rate"]
        tight = score_recording(events, slo_ms=50.0)["service"]["slo_violation_rate"]
        assert tight > loose


class TestDetection:
    def test_zt_sdn_names_and_cuts_off_both_attackers(self, tmp_path):
        _, events, _ = _record(tmp_path, "zt_sdn", "both")
        det = score_recording(events)["detection"]
        assert det["attackers"] == 2
        assert det["attackers_named"] == 2
        assert det["attackers_cut_off"] == 2
        assert det["honest_mislabelled"] == 0
        assert det["honest_quarantined"] == 0

    def test_a_trust_blind_strategy_keeps_feeding_flagged_attackers(self, tmp_path):
        _, events, _ = _record(tmp_path, "round_robin", "both")
        scores = score_recording(events)
        attackers = [s for s in scores["subjects"] if s["truth"] != "none"]
        assert all(s["quarantined_at_s"] is not None for s in attackers)
        assert all(s["routed_after_quarantine"] > 0 for s in attackers)
        assert scores["detection"]["attackers_cut_off"] == 0
        assert scores["service"]["attacker_share"] == pytest.approx(0.25, abs=0.02)

    def test_routed_after_counts_from_the_given_time(self):
        events = [
            {"type": "route", "ts": 1.0, "chosen": "srv1"},
            {"type": "route", "ts": 2.0, "chosen": "srv1"},
            {"type": "route", "ts": 3.0, "chosen": "srv2"},
        ]
        assert routed_after(events, "srv1", 2.0) == 1
        assert routed_after(events, "srv2", 0.0) == 1

    def test_a_clean_run_has_no_attackers(self, tmp_path):
        _, events, _ = _record(tmp_path, "zt_sdn", "clean")
        scores = score_recording(events)
        assert scores["detection"]["attackers"] == 0
        assert scores["service"]["attacker_share"] == 0.0

    def test_scores_a_recording_from_another_system(self):
        # The hand-written sample is not a simulator run: it has IoT devices,
        # an onset at 120 s and a live-style route_denied.
        events = read_events(EVENTS / "sample_run.jsonl")
        scores = score_recording(events)
        srv3 = next(s for s in scores["subjects"] if s["subject"] == "srv3")
        assert srv3["truth"] == "on_off"
        assert srv3["quarantined_at_s"] == 136.0
        assert srv3["isolation_latency_s"] == pytest.approx(16.0)


class TestCommand:
    def test_summary(self, turncoat, tmp_path):
        path, _, _ = _record(tmp_path, "zt_sdn", "both")
        code, out = turncoat("score", str(path))
        assert code == EXIT_OK
        assert "strategy zt_sdn, scenario both, seed 7" in out
        assert "Tasks offered" in out
        assert "named correctly" in out
        assert "2 of 2 attackers named correctly" in out

    def test_json_is_stable_and_parseable(self, turncoat, tmp_path):
        path, _, _ = _record(tmp_path, "zt_sdn", "both")
        _, first = turncoat("score", str(path), "--json")
        _, second = turncoat("score", str(path), "--json")
        assert first == second
        data = json.loads(first)
        assert set(data) == {"recording", "service", "detection", "subjects"}

    def test_detail_adds_the_full_attack_report(self, turncoat, tmp_path):
        path, _, _ = _record(tmp_path, "zt_sdn", "both")
        code, out = turncoat("score", str(path), "--detail")
        assert code == EXIT_OK
        assert "ATTACK CLASSIFICATION REPORT" in out

    def test_invalid_recording_is_refused(self, turncoat):
        code, out = turncoat("score", str(EVENTS / "broken_run.jsonl"))
        assert code == EXIT_FAILED
        assert "--skip-validation" in out

    def test_skip_validation_scores_anyway(self, turncoat, tmp_path):
        path, _, _ = _record(tmp_path, "zt_sdn", "drop")
        with open(path, "a", encoding="utf-8") as f:
            f.write("truncated tail\n")
        code, _ = turncoat("score", str(path))
        assert code == EXIT_FAILED
        code, out = turncoat("score", str(path), "--skip-validation")
        assert code == EXIT_OK
        assert "Tasks offered" in out

    def test_no_ground_truth_cannot_be_scored(self, turncoat, tmp_path):
        path = tmp_path / "no-topology.jsonl"
        path.write_text('{"type": "header", "schema_version": "1.0", "backend": "sim"}\n')
        code, out = turncoat("score", str(path), "--skip-validation")
        assert code == EXIT_FAILED
        assert "no topology event" in out

    def test_missing_file_exits_2(self, turncoat, tmp_path):
        code, out = turncoat("score", str(tmp_path / "missing.jsonl"))
        assert code == EXIT_UNREADABLE
        assert "cannot read" in out

    def test_bad_slo_is_refused(self, turncoat, tmp_path):
        path, _, _ = _record(tmp_path, "random", "clean")
        code, out = turncoat("score", str(path), "--slo-ms", "0")
        assert code == EXIT_FAILED
        assert "--slo-ms" in out
