"""Load-balancing strategies behind one ``Strategy`` interface:
random, round_robin, least_conn, no_trust and zt_sdn.

Owner: arv (Strategies, scoring and statistics track).
Lands in: v0.1.
Ported from the final-year project:
evaluation/baseline.py (strategy half).

This module must not import os-ken, Ryu or Mininet.
"""
