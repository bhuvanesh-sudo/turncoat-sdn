"""Seeded discrete-event simulator of edge servers, IoT clients and a strategy.

Owner: bv (Simulator track).
Lands in: v0.1.
Ported from the final-year project:
evaluation/baseline.py (simulator half); event writer in v0.2.

The simulator owns the network, the clients and the attackers. Routing, trust
and the latency tell are hooks passed in by the caller (see
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

from turncoat_sdn.sim.config import SCENARIOS, SimConfig, malicious_roles
from turncoat_sdn.sim.engine import UNTRUSTED_DEFAULT, run_paired, simulate
from turncoat_sdn.sim.hooks import (
    LatencyTell,
    Outcome,
    Router,
    RouterFactory,
    TellResult,
    TrustModel,
    TrustModelFactory,
)
from turncoat_sdn.sim.result import CSV_FIELDS, METRICS, RunResult, as_rows, gini, write_csv

__all__ = [
    "CSV_FIELDS",
    "METRICS",
    "SCENARIOS",
    "UNTRUSTED_DEFAULT",
    "LatencyTell",
    "Outcome",
    "Router",
    "RouterFactory",
    "RunResult",
    "SimConfig",
    "TellResult",
    "TrustModel",
    "TrustModelFactory",
    "as_rows",
    "gini",
    "malicious_roles",
    "run_paired",
    "simulate",
    "write_csv",
]
