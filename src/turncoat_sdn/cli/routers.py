"""The five strategies ``turncoat run`` can drive, as simulator routers.

Each entry builds a router in the shape of :class:`turncoat_sdn.sim.Router`.
They copy the routers of the final-year project's ``evaluation/baseline.py``
line for line, the same code the golden-file tests in ``tests/sim`` and
``tests/trust`` drive, so a CLI run reproduces the project's numbers.
``tests/cli/test_routers.py`` checks that against both golden files.

``no_trust`` and ``zt_sdn`` call the real :func:`select_edge_node`; they differ
only in whether trust and the anomaly gate are used. When
:mod:`turncoat_sdn.strategies` grows a simulator adapter, this table should
point at it instead.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import itertools
import random

from turncoat_sdn.sim import Router, RouterFactory
from turncoat_sdn.trust import (
    DEFAULT_ANOMALY_GATE,
    DEFAULT_ISOLATION_THRESHOLD,
    STRATEGY_P2C,
    EdgeWeights,
    NodeState,
    select_edge_node,
)

#: EdgeScore weights, exploration rate and sample size, as shipped in
#: ``evaluation/baseline.py``.
WEIGHTS = EdgeWeights(0.50, 0.30, 0.20)
EPSILON = 0.05
D_CHOICES = 2


def random_router(n: int, rng: random.Random) -> Router:
    """Uniform over all nodes: the null baseline."""

    class Random:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return rng.randrange(n)

    return Random()


def round_robin_router(n: int, rng: random.Random) -> Router:
    """Strict cycle: trust-blind and perfectly fair, so an attacker keeps its 1/N share."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def least_conn_router(n: int, rng: random.Random) -> Router:
    """Join-shortest-queue on *claimed* load, ties broken at random.

    The strongest classical baseline, and the one a Sybil exploits directly.
    """

    class LeastConn:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            lowest = min(claimed_cpu)
            candidates = [i for i, c in enumerate(claimed_cpu) if c <= lowest + 1e-9]
            return rng.choice(candidates)

    return LeastConn()


def _edge_score_router(use_trust: bool) -> RouterFactory:
    def factory(n: int, rng: random.Random) -> Router:
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
                if chosen is None:
                    return None
                return int(chosen[3:]) - 1

        return EdgeScore()

    return factory


no_trust_router = _edge_score_router(use_trust=False)
no_trust_router.__doc__ = "EdgeScore with trust and quarantine removed: the ablation."
zt_sdn_router = _edge_score_router(use_trust=True)
zt_sdn_router.__doc__ = "The full system: EdgeScore, real trust, isolation threshold and gate."

#: Strategy name, as used on the command line and in recordings, to router.
STRATEGIES: dict[str, RouterFactory] = {
    "random": random_router,
    "round_robin": round_robin_router,
    "least_conn": least_conn_router,
    "no_trust": no_trust_router,
    "zt_sdn": zt_sdn_router,
}

#: One line per strategy for ``turncoat run --help`` and docs/cli.md.
DESCRIPTIONS: dict[str, str] = {
    "random": "uniform over all servers",
    "round_robin": "strict cycle, trust-blind",
    "least_conn": "fewest claimed connections",
    "no_trust": "EdgeScore without trust or quarantine",
    "zt_sdn": "EdgeScore with trust and the anomaly gate",
}
