"""A stand-in recorder: turn a simulated run into an attack-scoring recording.

The simulator learns to write ``events.jsonl`` in v0.2 (bv, against arj's
schema). Until then this records the events the attack scorer reads, in the
shape the final-year project's controller wrote them:

* one ``topology`` event with every server's ground-truth ``attack`` and
  ``attack_start_s`` (0.0: the v0.1 simulator's attackers are hostile from the
  first second),
* per poll, an ``anomaly`` event for each node a detector flagged, with
  structured ``signals``,
* per poll, a ``node_status`` heartbeat that closes the cycle.

It reads nothing private. It wraps the simulator's ``latency_tell`` hook, which
is called once per poll for the fleet baseline and then once per node in
index order, and its ``trust`` hook, which sees every finished task. The
timeout-rate tell is rebuilt from those outcomes with the same window, sample
floor and threshold as :class:`turncoat_sdn.sim.SimConfig`. When the
simulator's own event writer lands, these tests should switch to it.
"""

from __future__ import annotations

import itertools
from collections import deque

import pytest

from turncoat_sdn.scoring.attack_classifier import SIG_LATENCY_TELL, SIG_PACKET_DROP
from turncoat_sdn.sim import SimConfig, malicious_roles, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell


def round_robin(n, rng):
    """Keeps feeding every node, so the detectors see attackers all run."""
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


def record_simulated_run(scenario, seed, *, router=round_robin, config=None):
    """Run the simulator once and return its attack-scoring recording."""
    cfg = config or SimConfig()
    n = cfg.n_nodes
    roles = malicious_roles(scenario, n)

    events = [
        {
            "ts": 0.0,
            "type": "topology",
            "graph": {
                "nodes": [
                    {
                        "id": f"srv{i + 1}",
                        "kind": "server",
                        "attack": roles.get(i, "none"),
                        "attack_start_s": 0.0,
                    }
                    for i in range(n)
                ],
                "links": [],
            },
        }
    ]
    recent = [deque(maxlen=cfg.recent_status_window) for _ in range(n)]
    poll = {"t": 0.0, "node": 0}

    class RecordingTrust(SimTrustModel):
        def update(self, outcome):
            recent[outcome.node].append(outcome.task_status)
            return super().update(outcome)

    class RecordingTell:
        def fleet_latency_baseline(self, rtts):
            # Called once at the start of every poll: open a new cycle.
            poll["t"] += cfg.poll_s
            poll["node"] = 0
            return latency_tell.fleet_latency_baseline(rtts)

        def evaluate_latency_tell(self, **kwargs):
            result = latency_tell.evaluate_latency_tell(**kwargs)
            i = poll["node"]
            poll["node"] += 1

            signals = {}
            if result.tripped:
                signals[SIG_LATENCY_TELL] = result.ratio
            history = recent[i]
            if len(history) >= cfg.min_timeout_samples:
                rate = sum(1 for s in history if s == "timeout") / len(history)
                if rate > cfg.honesty_deviation_threshold:
                    signals[SIG_PACKET_DROP] = rate
            if signals:
                events.append(
                    {"ts": poll["t"], "type": "anomaly", "node": f"srv{i + 1}", "signals": signals}
                )
            if i == n - 1:
                events.append({"ts": poll["t"], "type": "node_status", "nodes": {}})
            return result

    run = simulate(
        router,
        scenario,
        seed,
        config=cfg,
        trust=RecordingTrust,
        latency_tell=RecordingTell(),
    )
    return events, run


@pytest.fixture
def simulated_recording():
    """``record_simulated_run(scenario, seed, ...) -> (events, run_result)``."""
    return record_simulated_run
