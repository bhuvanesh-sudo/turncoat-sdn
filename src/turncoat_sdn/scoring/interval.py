"""Time-bucket aggregation for timestamped metric samples."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import floor, isfinite


def _finite_number(value: object) -> bool:
    """Return whether a value is a finite real number, excluding booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def score_intervals(
    samples: Sequence[Mapping[str, float]],
    *,
    interval_s: float,
    timestamp_key: str = "timestamp_s",
) -> list[dict[str, float | int]]:
    """Group timestamped samples into fixed-width intervals and average metrics.

    Interval indices start at zero and are based on elapsed time from t=0.
    Each sample must contain a finite non-negative timestamp and at least
    one finite numeric metric.
    """
    if not _finite_number(interval_s) or interval_s <= 0:
        raise ValueError("interval_s must be a finite positive number")

    buckets: dict[int, dict[str, list[float]]] = {}

    for sample in samples:
        timestamp = sample.get(timestamp_key)

        if not _finite_number(timestamp) or timestamp < 0:
            raise ValueError(f"{timestamp_key} must be a finite non-negative number")

        index = floor(timestamp / interval_s)
        metrics = {key: value for key, value in sample.items() if key != timestamp_key}

        if not metrics:
            raise ValueError("each sample must contain at least one metric")

        for key, value in metrics.items():
            if not _finite_number(value):
                raise ValueError(f"metric {key!r} must be a finite number")

            buckets.setdefault(index, {}).setdefault(key, []).append(float(value))

    results: list[dict[str, float | int]] = []

    for index in sorted(buckets):
        row: dict[str, float | int] = {
            "interval_index": index,
            "start_s": index * interval_s,
            "end_s": (index + 1) * interval_s,
        }

        for key, values in sorted(buckets[index].items()):
            row[key] = sum(values) / len(values)

        results.append(row)

    return results
