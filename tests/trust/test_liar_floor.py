"""The liar floor: why the trust formula needs an independent anomaly gate.

A node that lies about its load but still completes tasks quickly keeps R near
1.0 and B near 0.96. Dishonesty can drive H to 0 and A to 1, but delta only
ever subtracts 0.15, so

    T = 0.35(1.0) + 0.25(0.96) + 0.25(0.0) - 0.15(1.0) = 0.44

which never crosses the 0.3 isolation threshold. These tests prove that against
the real calculator, not a mock. ``test_f04_non_degrading_liar_needs_anomaly_gate``
is the final-year project's F-04 from ``tests/test_trust_state.py``, with the
controller's ``TrustState`` replaced by the calculator and ``is_quarantined``
it wrapped.
"""

from __future__ import annotations

import itertools

import pytest

from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import (
    DEFAULT_ANOMALY_GATE,
    DEFAULT_ISOLATION_THRESHOLD,
    NodeState,
    SimTrustModel,
    TrustCalculator,
    TrustUpdate,
    is_quarantined,
)

#: The floor from the design note: R=1, B=0.96, H=0, A=1.
LIAR_FLOOR = 0.35 * 1.0 + 0.25 * 0.96 + 0.25 * 0.0 - 0.15 * 1.0


def _liar(latency_ms=20.0, anomaly=True):
    """A task served successfully and fast by a node claiming 0.05 load while at 0.95."""
    return TrustUpdate(
        device_id="iot1",
        edge_node_id="srv1",
        task_status="success",
        cpu_usage=0.95,
        reported_cpu=0.05,
        latency_ms=latency_ms,
        anomaly_flag=anomaly,
    )


def test_the_floor_is_0_44():
    assert LIAR_FLOOR == pytest.approx(0.44)


def test_a_fully_flagged_liar_converges_to_the_floor():
    """Every dishonesty signal maxed out, and trust still settles at 0.44."""
    calc = TrustCalculator()
    for _ in range(60):
        calc.update(_liar())

    c = calc.get_components("srv1")
    assert c["R"] == pytest.approx(1.0)
    assert c["B"] == pytest.approx(0.96)
    assert c["H"] == pytest.approx(0.0)
    assert c["A"] == pytest.approx(1.0)
    assert calc.get_score("srv1") == pytest.approx(LIAR_FLOOR)


def test_the_liar_never_crosses_the_isolation_threshold():
    """Not even on the way down from the initial score."""
    calc = TrustCalculator()
    scores = [calc.update(_liar()) for _ in range(60)]
    assert min(scores) > DEFAULT_ISOLATION_THRESHOLD


@pytest.mark.parametrize("latency_ms", [0.0, 5.0, 10.0, 20.0])
def test_a_faster_liar_floors_even_higher(latency_ms):
    calc = TrustCalculator()
    for _ in range(60):
        calc.update(_liar(latency_ms=latency_ms))
    assert calc.get_score("srv1") >= LIAR_FLOOR - 1e-12


def test_f04_non_degrading_liar_needs_anomaly_gate():
    """A node that always succeeds fast but lies about its CPU load.

    Honesty delta drives H down, but delta=0.15 can only ever subtract 0.15, so
    trust alone floats well above the 0.3 isolation threshold. The anomaly
    gate, fed by the controller's honesty or latency tell, is what actually
    excludes it.
    """
    calc = TrustCalculator(alpha=0.35, beta=0.25, gamma=0.25, delta=0.15, lambda_decay=0.85)
    for _ in range(30):
        calc.update(_liar(latency_ms=5, anomaly=False))

    trust = calc.get_score("srv1")
    assert trust > DEFAULT_ISOLATION_THRESHOLD, (
        f"expected the formula alone to float above the isolation threshold (got {trust:.4f}) "
        "-- if this fails the formula itself changed and this test needs revisiting"
    )
    calm = NodeState("srv1", trust=trust, cpu_load=0.05, latency_ms=5, anomaly=0.0)
    assert not is_quarantined(calm), "trust-only check should NOT catch this liar"

    # The tell fires once. The controller smooths the raw flag with the same
    # 0.85 EMA, so one sample already reaches the gate.
    flagged = NodeState("srv1", trust=trust, cpu_load=0.05, latency_ms=5, anomaly=0.85 * 1.0)
    assert flagged.anomaly >= DEFAULT_ANOMALY_GATE
    assert is_quarantined(flagged), "anomaly gate must catch what trust alone cannot"


def test_an_honest_dropper_also_floors_above_the_line_without_the_gate():
    """The same blind spot for the dropper, from ``evaluation/baseline.py``.

    A node that times out every task but reports its CPU honestly settles at
    T = 0.35(0.3) + 0.25(0.0) + 0.25(1.0) = 0.355 while nothing flags it.
    """
    calc = TrustCalculator()
    for _ in range(60):
        calc.update(
            TrustUpdate(
                device_id="iot1",
                edge_node_id="srv1",
                task_status="timeout",
                cpu_usage=0.5,
                reported_cpu=0.5,
                latency_ms=2000.0,
            )
        )
    assert calc.get_score("srv1") == pytest.approx(0.355)
    assert calc.get_score("srv1") > DEFAULT_ISOLATION_THRESHOLD


def test_in_the_simulator_trust_alone_never_isolates_the_sybil():
    """End to end: the simulated Sybil keeps its trust above 0.3 all run.

    Round-robin keeps feeding the Sybil its share, so its trust is updated
    throughout the run. With no latency tell there is no anomaly evidence,
    and the trust score alone never excludes it.
    """
    sybil_trust = []

    def recording_round_robin(n, rng):
        cycle = itertools.cycle(range(n))

        class Recorder:
            def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                sybil_trust.append(trust[n - 1])
                return next(cycle)

        return Recorder()

    run = simulate(recording_round_robin, "sybil", 1000, trust=SimTrustModel)
    assert run.time_to_isolate_s is None
    assert len(set(sybil_trust)) > 1, "the Sybil's trust was never updated"
    assert min(sybil_trust) > DEFAULT_ISOLATION_THRESHOLD
