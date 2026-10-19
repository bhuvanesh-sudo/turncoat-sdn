"""Reference routers for the simulator tests.

These copy the three trust-blind baselines from the final-year project's
``evaluation/baseline.py`` so the simulator can be tested before
``turncoat_sdn.strategies`` exists. They read nothing but claimed load, which
is why the golden numbers do not depend on a trust model or latency tell.
"""

from __future__ import annotations

import itertools

import pytest


def random_router(n, rng):
    class Random:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return rng.randrange(n)

    return Random()


def round_robin_router(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def least_conn_router(n, rng):
    class LeastConn:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            # Join-shortest-queue on what the nodes *claim*, ties broken at random.
            lowest = min(claimed_cpu)
            candidates = [i for i, c in enumerate(claimed_cpu) if c <= lowest + 1e-9]
            return rng.choice(candidates)

    return LeastConn()


ROUTERS = {
    "random": random_router,
    "round_robin": round_robin_router,
    "least_conn": least_conn_router,
}


@pytest.fixture
def routers():
    """The trust-blind reference routers, keyed by their FYP strategy name."""
    return dict(ROUTERS)
