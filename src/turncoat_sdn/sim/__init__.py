"""Seeded discrete-event simulator of edge servers, IoT clients and a strategy.

Owner: bv (Simulator track).
Lands in: v0.1.
Ported from the final-year project:
evaluation/baseline.py (simulator half); recording to events.jsonl in v0.2.

The simulator owns the network, the clients and the attackers; how each
attacker behaves, and when it turns, comes from :mod:`turncoat_sdn.attacks`.
In a run with a client attacker it also owns the controller's admission check
(:mod:`turncoat_sdn.sim.admission`).
Routing, trust and the latency tell are hooks passed in by the caller (see
:mod:`turncoat_sdn.sim.hooks`), so this package needs nothing from the
controller. A minimal run::

    from turncoat_sdn.sim import simulate

    def uniform(n, rng):
        class Uniform:
            def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
                return rng.randrange(n)
        return Uniform()

    result = simulate(uniform, "drop", seed=1)
    print(result.slo_violation_rate)

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.sim.admission import BINDINGS, IdentityBinding, client_id, client_ip
from turncoat_sdn.sim.config import (
    SCENARIOS,
    SimConfig,
    malicious_roles,
    scenario_attacks,
    scenario_client_attacks,
)
from turncoat_sdn.sim.detect import (
    SIGNAL_LATENCY_TELL,
    SIGNAL_PACKET_DROP,
    DetectionSettings,
    detect_anomalies,
    is_excluded,
)
from turncoat_sdn.sim.engine import UNTRUSTED_DEFAULT, node_id, run_paired, simulate
from turncoat_sdn.sim.hooks import (
    LatencyTell,
    Outcome,
    Recorder,
    RecorderFactory,
    Router,
    RouterFactory,
    TellResult,
    TrustModel,
    TrustModelFactory,
)
from turncoat_sdn.sim.result import CSV_FIELDS, METRICS, RunResult, as_rows, gini, write_csv

__all__ = [
    "BINDINGS",
    "CSV_FIELDS",
    "DetectionSettings",
    "METRICS",
    "SCENARIOS",
    "SIGNAL_LATENCY_TELL",
    "SIGNAL_PACKET_DROP",
    "UNTRUSTED_DEFAULT",
    "IdentityBinding",
    "LatencyTell",
    "Outcome",
    "Recorder",
    "RecorderFactory",
    "Router",
    "RouterFactory",
    "RunResult",
    "SimConfig",
    "TellResult",
    "TrustModel",
    "TrustModelFactory",
    "as_rows",
    "client_id",
    "client_ip",
    "detect_anomalies",
    "gini",
    "is_excluded",
    "malicious_roles",
    "node_id",
    "run_paired",
    "scenario_attacks",
    "scenario_client_attacks",
    "simulate",
    "write_csv",
]
