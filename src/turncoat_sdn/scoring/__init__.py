"""Scorers that grade a recording: attack (confusion matrix, detection latency),
NFR, interval and availability.

Owner: arv; attack scoring by ash.
Lands in: v0.2.
Ported from the final-year project:
evaluation/attack_report.py, nfr_report.py, interval_report.py,
availability_report.py, controller/attack_classifier.py.

This module must not import os-ken, Ryu or Mininet.
"""

from turncoat_sdn.scoring.availability import score_availability
from turncoat_sdn.scoring.interval import score_intervals
from turncoat_sdn.scoring.nfr import score_nfr

__all__ = [
    "score_availability",
    "score_intervals",
    "score_nfr",
]
