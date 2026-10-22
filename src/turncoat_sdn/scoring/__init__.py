"""Scorers that grade a recording: attack (confusion matrix, detection latency),
NFR, interval and availability.

Owner: arv; attack scoring by ash.
Lands in: v0.2.
Ported from the final-year project:
evaluation/attack_report.py, nfr_report.py, interval_report.py,
availability_report.py, controller/attack_classifier.py.

Attack scoring replays a recording's detector evidence through the attack
classifier and scores the labels against the ground truth in its ``topology``
event::

    from turncoat_sdn.scoring.attack_report import format_report, score_run

    print(format_report(score_run(events)))

The attack report is imported from its own module rather than re-exported
here, so ``python -m turncoat_sdn.scoring.attack_report`` runs cleanly.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.scoring.attack_classifier import (
    ALL_LABELS,
    ATTACK_FAMILIES,
    AttackEvidence,
    Classification,
    Observation,
    classify_client,
    classify_node,
    family_of,
)
from turncoat_sdn.scoring.availability import score_availability
from turncoat_sdn.scoring.interval import score_intervals
from turncoat_sdn.scoring.nfr import score_nfr

__all__ = [
    "ALL_LABELS",
    "ATTACK_FAMILIES",
    "AttackEvidence",
    "Classification",
    "Observation",
    "classify_client",
    "classify_node",
    "family_of",
    "score_availability",
    "score_intervals",
    "score_nfr",
]
