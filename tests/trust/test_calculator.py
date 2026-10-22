"""The trust calculator, moved from ``trust_engine/trust_calculator.py``.

T-01 to T-07 are the final-year project's ``tests/test_trust.py``, with only
the import paths changed. The ``SimTrustModel`` tests are new: they check the
calculator fills the simulator's trust hook the way ``evaluation/baseline.py``
called it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from turncoat_sdn.sim import Outcome, SimConfig, simulate
from turncoat_sdn.trust import SimTrustModel, TrustCalculator, TrustUpdate


def _make_update(
    node_id: str = "srv1",
    status: str = "success",
    cpu: float = 0.3,
    reported_cpu: float = 0.3,
    latency: float = 20.0,
    anomaly: bool = False,
) -> TrustUpdate:
    """Helper to create a TrustUpdate with sensible defaults."""
    return TrustUpdate(
        device_id="iot_test",
        edge_node_id=node_id,
        task_status=status,
        cpu_usage=cpu,
        reported_cpu=reported_cpu,
        latency_ms=latency,
        anomaly_flag=anomaly,
    )


class TestTrustCalculator:
    """T-01 through T-07."""

    def test_t01_good_node_converges_high(self):
        """T-01: 20 success updates, honesty_delta=0, no anomaly -> T > 0.80.

        The formula's maximum is alpha + beta + gamma = 0.85 (when A=0), so the
        threshold is 0.80.
        """
        tc = TrustCalculator()
        for _ in range(20):
            tc.update(_make_update(cpu=0.3, reported_cpu=0.3, latency=0.0))
        assert tc.get_score("srv1") > 0.80

    def test_t02_bad_node_converges_low(self):
        """T-02: 20 failure updates, anomaly_flag=True -> T < 0.10."""
        tc = TrustCalculator()
        for _ in range(20):
            tc.update(
                _make_update(
                    status="failure", cpu=0.8, reported_cpu=0.1, latency=400.0, anomaly=True
                )
            )
        assert tc.get_score("srv1") < 0.10

    def test_t03_weights_dont_sum_to_one(self):
        """T-03: Weights that don't sum to 1.0 -> AssertionError."""
        with pytest.raises(AssertionError):
            TrustCalculator(alpha=0.5, beta=0.5, gamma=0.5, delta=0.5)

    def test_t04_unseen_node_returns_initial(self):
        """T-04: Query node before first update -> returns 0.5."""
        tc = TrustCalculator()
        assert tc.get_score("srv_unseen") == 0.5

    def test_t05_trust_drops_then_recovers(self):
        """T-05: 10 good -> 1 malicious -> 5 good: trust drops, then recovers."""
        tc = TrustCalculator()
        for _ in range(10):
            tc.update(_make_update())
        before_attack = tc.get_score("srv1")

        tc.update(
            _make_update(status="failure", cpu=0.9, reported_cpu=0.1, latency=450.0, anomaly=True)
        )
        after_attack = tc.get_score("srv1")

        for _ in range(5):
            tc.update(_make_update())
        after_recovery = tc.get_score("srv1")

        assert after_attack < before_attack
        assert after_recovery > after_attack

    def test_t06_extreme_inputs_stay_bounded(self):
        """T-06: Extreme inputs (all 0s, all 1s) -> T always in [0, 1]."""
        tc = TrustCalculator()
        for _ in range(10):
            score = tc.update(
                _make_update(
                    status="failure", cpu=0.0, reported_cpu=1.0, latency=1000.0, anomaly=True
                )
            )
            assert 0.0 <= score <= 1.0
        for _ in range(10):
            score = tc.update(_make_update(node_id="srv2", cpu=1.0, reported_cpu=1.0, latency=0.0))
            assert 0.0 <= score <= 1.0

    def test_t07_honesty_delta_high_pushes_h_low(self):
        """T-07: honesty_delta = 0.5 -> a dishonest node scores below an honest one."""
        dishonest = TrustCalculator()
        for _ in range(20):
            dishonest.update(_make_update(cpu=0.7, reported_cpu=0.2))  # delta = 0.5

        honest = TrustCalculator()
        for _ in range(20):
            honest.update(_make_update(cpu=0.3, reported_cpu=0.3))  # delta = 0.0

        assert dishonest.get_score("srv1") < honest.get_score("srv1")
        assert dishonest.get_components("srv1")["H"] < 0.01


class TestTrustUpdate:
    def test_update_records_the_score_before_and_after(self):
        tc = TrustCalculator()
        upd = _make_update()
        score = tc.update(upd)
        assert upd.trust_score_before == 0.5
        assert upd.trust_score_after == score

    def test_honesty_delta_is_the_absolute_gap(self):
        assert _make_update(cpu=0.9, reported_cpu=0.1).honesty_delta() == pytest.approx(0.8)
        assert _make_update(cpu=0.1, reported_cpu=0.9).honesty_delta() == pytest.approx(0.8)

    def test_an_unknown_status_counts_like_a_timeout(self):
        timeout, unknown = TrustCalculator(), TrustCalculator()
        timeout.update(_make_update(status="timeout"))
        unknown.update(_make_update(status="lost"))
        assert unknown.get_score("srv1") == timeout.get_score("srv1")


class TestComponents:
    def test_unseen_node_has_the_starting_components(self):
        assert TrustCalculator().get_components("srv9") == {
            "R": 0.5,
            "B": 0.5,
            "H": 0.5,
            "A": 0.0,
        }

    def test_components_are_a_copy(self):
        tc = TrustCalculator()
        tc.update(_make_update())
        tc.get_components("srv1")["R"] = -1.0
        assert tc.get_components("srv1")["R"] > 0.0

    def test_score_is_the_weighted_sum_of_the_components(self):
        tc = TrustCalculator()
        for latency in (10.0, 80.0, 300.0):
            tc.update(_make_update(cpu=0.6, reported_cpu=0.2, latency=latency, anomaly=True))
        c = tc.get_components("srv1")
        expected = 0.35 * c["R"] + 0.25 * c["B"] + 0.25 * c["H"] - 0.15 * c["A"]
        assert tc.get_score("srv1") == pytest.approx(expected)


def _outcome(**overrides):
    fields = dict(
        node=0,
        edge_node_id="srv1",
        timestamp=12.5,
        task_status="success",
        cpu_usage=0.95,
        reported_cpu=0.05,
        latency_ms=20.0,
        anomaly_flag=True,
    )
    fields.update(overrides)
    return Outcome(**fields)


class TestSimTrustModel:
    def test_starts_every_node_at_the_calculator_initial_score(self):
        assert SimTrustModel().initial_score == 0.5
        assert SimTrustModel(TrustCalculator(initial_score=0.7)).initial_score == 0.7

    def test_scores_an_outcome_like_the_equivalent_trust_update(self):
        model, direct = SimTrustModel(), TrustCalculator()
        for _ in range(5):
            got = model.update(_outcome())
            want = direct.update(
                TrustUpdate(
                    device_id="sim",
                    edge_node_id="srv1",
                    task_status="success",
                    cpu_usage=0.95,
                    reported_cpu=0.05,
                    latency_ms=20.0,
                    anomaly_flag=True,
                )
            )
            assert got == want

    def test_keeps_nodes_apart(self):
        model = SimTrustModel()
        model.update(_outcome(edge_node_id="srv1", task_status="timeout"))
        model.update(_outcome(node=1, edge_node_id="srv2", anomaly_flag=False, reported_cpu=0.95))
        scores = model.calculator.get_all_scores()
        assert set(scores) == {"srv1", "srv2"}
        assert scores["srv2"] > scores["srv1"]

    def test_the_class_is_a_trust_hook_factory(self, routers):
        """Passed as ``trust=SimTrustModel``, each run gets a fresh model."""
        short = replace(SimConfig(), sim_s=10.0, n_nodes=4)
        first = simulate(routers["round_robin"], "drop", 3, config=short, trust=SimTrustModel)
        second = simulate(routers["round_robin"], "drop", 3, config=short, trust=SimTrustModel)
        assert first == second
