"""Descriptive benchmark summaries for v0.3 strategy comparisons.

This module is additive: it does not modify the existing attack scorer.
It aggregates scored recordings without performing v0.4 statistical tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from turncoat_sdn.scoring.attack_report import score_run


@dataclass(frozen=True)
class BenchmarkSummary:
    """Aggregate detection metrics for a collection of scored recordings."""

    name: str
    runs: int
    attack_subjects: int
    detected_attacks: int
    missed_attacks: int
    detection_rate: float | None
    honest_subjects: int
    false_positives: int
    false_positive_rate: float | None
    mean_detection_latency_s: float | None


def summarize_results(
    name: str,
    results_by_run: Iterable[Sequence[Any]],
) -> BenchmarkSummary:
    """Summarize existing SubjectResult sequences from one strategy.

    An attack is detected when its final predicted label matches its ground
    truth. An honest subject is a false positive when it receives any attack
    label. Latency averages only attacks that were correctly detected and
    have a known, non-negative detection latency.
    """
    runs = 0
    attack_subjects = detected_attacks = 0
    honest_subjects = false_positives = 0
    latencies: list[float] = []

    for results in results_by_run:
        runs += 1
        for result in results:
            if result.truth == "none":
                honest_subjects += 1
                if result.predicted != "none":
                    false_positives += 1
                continue

            attack_subjects += 1
            if result.correct:
                detected_attacks += 1
                latency = result.detection_latency_s
                if latency is not None and latency >= 0:
                    latencies.append(float(latency))

    missed = attack_subjects - detected_attacks
    return BenchmarkSummary(
        name=name,
        runs=runs,
        attack_subjects=attack_subjects,
        detected_attacks=detected_attacks,
        missed_attacks=missed,
        detection_rate=(detected_attacks / attack_subjects if attack_subjects else None),
        honest_subjects=honest_subjects,
        false_positives=false_positives,
        false_positive_rate=(false_positives / honest_subjects if honest_subjects else None),
        mean_detection_latency_s=(sum(latencies) / len(latencies) if latencies else None),
    )


def summarize_recordings(
    recordings: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[BenchmarkSummary]:
    """Score each named recording and summarize its results."""
    return [
        summarize_results(name, [score_run(events)]) for name, events in sorted(recordings.items())
    ]


def write_json(
    summaries: Sequence[BenchmarkSummary],
    path: str | Path,
) -> None:
    """Write benchmark summaries as portable JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps([asdict(summary) for summary in summaries], indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(
    summaries: Sequence[BenchmarkSummary],
    path: str | Path,
) -> None:
    """Write benchmark summaries as CSV."""
    import csv

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(summary) for summary in summaries]
    fields = list(BenchmarkSummary.__dataclass_fields__)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
