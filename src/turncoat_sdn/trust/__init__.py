"""Trust calculator, edge selector, thresholds and the anomaly gate.

Owner: ash (Trust model and attacks track); latency tell moved by arj.
Lands in: v0.1.
Ported from the final-year project:
trust_engine/trust_calculator.py, controller/edge_selector.py,
contracts/thresholds.py, and evaluate_latency_tell / fleet_latency_baseline
from controller/flow_monitor.py.

Two modules fill the simulator's hooks as they are. Pass
:class:`SimTrustModel` as ``trust`` and :mod:`turncoat_sdn.trust.latency_tell`
as ``latency_tell``::

    from turncoat_sdn.sim import simulate
    from turncoat_sdn.trust import SimTrustModel, latency_tell

    result = simulate(router, "both", seed=1, trust=SimTrustModel, latency_tell=latency_tell)

Routers rank nodes with :func:`select_edge_node`, which applies the isolation
threshold and the anomaly gate before scoring.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.trust import latency_tell
from turncoat_sdn.trust.calculator import SimTrustModel, TrustCalculator, TrustUpdate
from turncoat_sdn.trust.edge_selector import (
    BAND_FULL,
    BAND_QUARANTINED,
    BAND_RATE_LIMITED,
    STRATEGY_ARGMAX,
    STRATEGY_P2C,
    EdgeWeights,
    NodeState,
    edge_score,
    is_quarantined,
    select_edge_node,
    trust_band,
)
from turncoat_sdn.trust.latency_tell import (
    LatencyTellResult,
    evaluate_latency_tell,
    fleet_latency_baseline,
)
from turncoat_sdn.trust.thresholds import (
    DEFAULT_ANOMALY_GATE,
    DEFAULT_ANOMALY_WARN,
    DEFAULT_ISOLATION_THRESHOLD,
    DEFAULT_RATE_LIMIT_TRUST,
)

__all__ = [
    "BAND_FULL",
    "BAND_QUARANTINED",
    "BAND_RATE_LIMITED",
    "DEFAULT_ANOMALY_GATE",
    "DEFAULT_ANOMALY_WARN",
    "DEFAULT_ISOLATION_THRESHOLD",
    "DEFAULT_RATE_LIMIT_TRUST",
    "STRATEGY_ARGMAX",
    "STRATEGY_P2C",
    "EdgeWeights",
    "LatencyTellResult",
    "NodeState",
    "SimTrustModel",
    "TrustCalculator",
    "TrustUpdate",
    "edge_score",
    "evaluate_latency_tell",
    "fleet_latency_baseline",
    "is_quarantined",
    "latency_tell",
    "select_edge_node",
    "trust_band",
]
