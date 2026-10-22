"""Reference routers for the trust tests.

``no_trust`` and ``zt_sdn`` copy the two EdgeScore strategies from the
final-year project's ``evaluation/baseline.py``, so the trust model can be
tested inside the simulator before ``turncoat_sdn.strategies`` exists. Both
call the real :func:`select_edge_node`; they differ only in whether trust and
the anomaly gate are used. ``round_robin`` is the trust-blind control.
"""

from __future__ import annotations

import itertools

import pytest

from turncoat_sdn.trust import (
    DEFAULT_ANOMALY_GATE,
    DEFAULT_ISOLATION_THRESHOLD,
    STRATEGY_P2C,
    EdgeWeights,
    NodeState,
    select_edge_node,
)

# As shipped in evaluation/baseline.py.
WEIGHTS = EdgeWeights(0.50, 0.30, 0.20)
EPSILON = 0.05
D_CHOICES = 2


def _edge_score_router(use_trust):
    def factory(n, rng):
        class EdgeScore:
            def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                if use_trust:
                    states = [
                        NodeState(f"srv{i + 1}", trust[i], claimed_cpu[i], rtt_ms[i], anomaly[i])
                        for i in range(n)
                    ]
                    isolation, gate = DEFAULT_ISOLATION_THRESHOLD, DEFAULT_ANOMALY_GATE
                else:
                    # Trust pinned high and uniform, quarantine switched off:
                    # what is left is load and latency.
                    states = [
                        NodeState(f"srv{i + 1}", 1.0, claimed_cpu[i], rtt_ms[i], 0.0)
                        for i in range(n)
                    ]
                    isolation, gate = 0.0, 2.0
                chosen, _, _ = select_edge_node(
                    states,
                    WEIGHTS,
                    isolation_threshold=isolation,
                    anomaly_gate=gate,
                    strategy=STRATEGY_P2C,
                    d_choices=D_CHOICES,
                    epsilon=EPSILON,
                    rng=rng,
                )
                return None if chosen is None else int(chosen[3:]) - 1

        return EdgeScore()

    return factory


def round_robin_router(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


ROUTERS = {
    "round_robin": round_robin_router,
    "no_trust": _edge_score_router(use_trust=False),
    "zt_sdn": _edge_score_router(use_trust=True),
}


@pytest.fixture
def routers():
    """Reference routers keyed by their final-year project strategy name."""
    return dict(ROUTERS)
