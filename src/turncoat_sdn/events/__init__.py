"""The shared ``events.jsonl`` format: schema, JSONL writer and reader, validator.

Owner: arj (Event format and live recording track).
Lands in: v0.2.
Ported from the final-year project:
controller/event_bus.py (JSONL part), evaluation/nfr_report.load_events.

This module must not import os-ken, Ryu or Mininet.
"""
