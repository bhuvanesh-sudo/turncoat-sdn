"""Descriptive statistics for repeated strategy benchmark runs.

This module provides descriptive summaries for v0.3. From v0.4,
``summarize_metrics(..., confidence=0.95)`` adds a bootstrap confidence
interval to each summary (see :mod:`turncoat_sdn.stats.bootstrap`). Inferential
tests remain out of scope.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from turncoat_sdn.stats.bootstrap import DEFAULT_RESAMPLES, bootstrap_ci


@dataclass(frozen=True)
class DescriptiveSummary:
    """Descriptive statistics for a sequence of numeric observations."""

    count: int
    mean: float | None
    sample_stddev: float | None
    minimum: float | None
    maximum: float | None


def summarize(values: Iterable[float]) -> DescriptiveSummary:
    """Calculate count, mean, sample standard deviation, minimum and maximum.

    Empty input produces null statistics. A single observation has a mean,
    minimum and maximum, but no sample standard deviation.
    """
    observations: list[float] = []

    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("observations must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("observations must be finite")
        observations.append(number)

    if not observations:
        return DescriptiveSummary(0, None, None, None, None)

    count = len(observations)
    mean = math.fsum(observations) / count
    sample_stddev = (
        math.sqrt(math.fsum((value - mean) ** 2 for value in observations) / (count - 1))
        if count > 1
        else None
    )

    return DescriptiveSummary(
        count=count,
        mean=mean,
        sample_stddev=sample_stddev,
        minimum=min(observations),
        maximum=max(observations),
    )


def summarize_metrics(
    records: Iterable[Mapping[str, Any]],
    *,
    group_by: tuple[str, ...] = ("strategy", "scenario"),
    metrics: tuple[str, ...] = (
        "detection_rate",
        "false_positive_rate",
        "mean_detection_latency_s",
    ),
    confidence: float | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Summarize numeric metrics by strategy/scenario or other grouping keys.

    Each input record represents one run. Missing or null metrics are skipped.
    Records missing a grouping key are rejected. Non-numeric metric values are
    rejected rather than silently ignored.

    With ``confidence`` (for example 0.95), each metric's summary also carries
    ``ci_low`` and ``ci_high``, a seeded percentile-bootstrap interval for its
    mean over ``resamples`` resamples.
    """
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}

    for record in records:
        missing = [key for key in group_by if key not in record]
        if missing:
            raise ValueError(f"record missing grouping keys: {', '.join(missing)}")
        key = tuple(record[field] for field in group_by)
        groups.setdefault(key, []).append(record)

    output: list[dict[str, Any]] = []

    for key, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        row: dict[str, Any] = dict(zip(group_by, key, strict=True))
        row["runs"] = len(group)

        for metric in metrics:
            values = [record[metric] for record in group if record.get(metric) is not None]
            row[metric] = asdict(summarize(values))
            if confidence is not None:
                interval = bootstrap_ci(
                    values, confidence=confidence, resamples=resamples, seed=seed
                )
                row[metric]["ci_low"] = interval.low
                row[metric]["ci_high"] = interval.high

        output.append(row)

    return output
