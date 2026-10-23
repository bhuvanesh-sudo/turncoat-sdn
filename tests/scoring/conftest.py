"""Record a real simulated run for the attack scorer.

The simulator writes ``events.jsonl`` itself from v0.2 (``simulate``'s
``recorder`` hook into :class:`turncoat_sdn.events.EventWriter`). These tests
score the file it writes, read back with the shared reader: the ``topology``
with every attacker's ground truth and onset (0.0: the built-in scenarios'
attackers are hostile from the first second), an ``anomaly`` event for each
node a detector flagged at a poll, with structured ``signals``, and a
``node_status`` heartbeat that closes every poll cycle.
"""

from __future__ import annotations

import itertools

import pytest

from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell


def round_robin(n, rng):
    """Keeps feeding every node, so the detectors see attackers all run."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


@pytest.fixture
def simulated_recording(tmp_path):
    """``record(scenario, seed, *, router=round_robin, config=None) -> (events, run_result)``."""

    def record(scenario, seed, *, router=round_robin, config=None):
        path = tmp_path / f"{scenario}-{seed}.jsonl"
        with EventWriter(
            path, backend="sim", seed=seed, strategy=router.__name__, scenario=scenario
        ) as rec:
            run = simulate(
                router,
                scenario,
                seed,
                config=config,
                trust=SimTrustModel,
                latency_tell=latency_tell,
                recorder=rec,
            )
        return read_events(path), run

    return record
