"""Trust calculator, edge selector, thresholds and the anomaly gate.

Owner: ash (Trust model and attacks track); latency tell moved by arj.
Lands in: v0.1.
Ported from the final-year project:
trust_engine/trust_calculator.py, controller/edge_selector.py,
contracts/thresholds.py, and evaluate_latency_tell / fleet_latency_baseline
from controller/flow_monitor.py.

This module must not import os-ken, Ryu or Mininet.
"""
