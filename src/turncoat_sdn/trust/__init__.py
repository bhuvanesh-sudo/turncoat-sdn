"""Trust calculator, edge selector, thresholds and the anomaly gate.

Owner: ash (Trust model and attacks track); latency tell moved by arj.
Lands in: v0.1.
Ported from the final-year project:
trust_engine/trust_calculator.py, controller/edge_selector.py,
contracts/thresholds.py, and evaluate_latency_tell / fleet_latency_baseline
from controller/flow_monitor.py.

The latency tell lives in :mod:`turncoat_sdn.trust.latency_tell`. Pass that
module to :func:`turncoat_sdn.sim.simulate` as its ``latency_tell`` hook.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.trust.latency_tell import (
    LatencyTellResult,
    evaluate_latency_tell,
    fleet_latency_baseline,
)

__all__ = [
    "LatencyTellResult",
    "evaluate_latency_tell",
    "fleet_latency_baseline",
]
