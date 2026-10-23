"""Non-functional requirement metrics for a benchmark run."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite


def score_nfr(record: Mapping[str, object]) -> dict[str, float | int]:
    """Calculate failure rate, SLO violation rate and latency from a run record.

    Required fields: offered, failed, slo_violations, latencies_ms.
    Rates use offered tasks as the denominator. Latency uses completed tasks.
    """
    offered = record.get("offered")
    failed = record.get("failed")
    violations = record.get("slo_violations")
    latencies = record.get("latencies_ms")

    if not isinstance(offered, int) or isinstance(offered, bool) or offered < 0:
        raise ValueError("offered must be a non-negative integer")
    if not isinstance(failed, int) or isinstance(failed, bool) or not 0 <= failed <= offered:
        raise ValueError("failed must be an integer between 0 and offered")
    if (
        not isinstance(violations, int)
        or isinstance(violations, bool)
        or not 0 <= violations <= offered
    ):
        raise ValueError("slo_violations must be an integer between 0 and offered")
    if not isinstance(latencies, (list, tuple)):
        raise ValueError("latencies_ms must be a list or tuple")

    values = list(latencies)
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("latencies must be finite, non-negative numbers")

    ordered = sorted(values)
    count = len(ordered)
    p95 = ordered[min(count - 1, int(0.95 * count))] if count else 0.0

    return {
        "offered": offered,
        "failed": failed,
        "failure_rate": failed / offered if offered else 0.0,
        "slo_violation_rate": violations / offered if offered else 0.0,
        "completed_latency_count": count,
        "mean_latency_ms": sum(values) / count if count else 0.0,
        "p95_latency_ms": float(p95),
    }
