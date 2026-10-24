"""What one run measures, and how it is written out as a row."""

from __future__ import annotations

import csv
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from os import PathLike
from typing import Any


def gini(values: Sequence[int]) -> float:
    """Gini coefficient of ``values``: 0 is perfectly even, near 1 is one node takes all."""
    xs = sorted(values)
    n, s = len(xs), sum(xs)
    if s == 0:
        return 0.0
    return (2 * sum((i + 1) * x for i, x in enumerate(xs)) - (n + 1) * s) / (n * s)


@dataclass
class RunResult:
    """Outcome of one seeded run of one strategy against one scenario."""

    strategy: str
    scenario: str
    seed: int
    offered: int = 0
    completed: int = 0
    failed: int = 0
    """Timed out, gave up in a backlog, or refused because every node was quarantined."""
    slo_violations: int = 0
    malicious_tasks: int = 0
    """Tasks routed to an attacker."""
    latencies_ms: list[float] = field(default_factory=list)
    """Latency of every completed task, in completion order."""
    served: list[int] = field(default_factory=list)
    """Tasks routed to each node, by index."""
    time_to_isolate_s: float | None = None
    """First poll at which every attacker was excluded, or ``None`` if never."""
    client_attack_requests: int = 0
    """Requests client attackers sent of their own, admitted or not."""
    client_attack_refused: int = 0
    """Of those, how many the admission check refused before routing."""
    honest_refused: int = 0
    """Ordinary requests refused because another address owned the sender's identity.

    Only ``tofu`` can do this, after a spoofer has claimed an identity first.
    Refused requests never reach the router, so none of these three counts
    is part of ``offered``.
    """

    @property
    def failure_rate(self) -> float:
        return self.failed / self.offered if self.offered else 0.0

    @property
    def slo_violation_rate(self) -> float:
        """Fraction of offered tasks that failed or finished slower than the SLO."""
        return self.slo_violations / self.offered if self.offered else 0.0

    @property
    def malicious_share(self) -> float:
        return self.malicious_tasks / self.offered if self.offered else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return statistics.fmean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]

    @property
    def gini(self) -> float:
        return gini(self.served)


#: Metrics exposed to the statistics layer. ``True`` means lower is better.
METRICS: dict[str, bool] = {
    "slo_violation_rate": True,
    "failure_rate": True,
    "malicious_share": True,
    "mean_latency_ms": True,
    "p95_latency_ms": True,
    "gini": True,
}

#: The per-run row schema, in column order. :func:`as_rows` and
#: :func:`write_csv` both use it, so in-memory rows and CSV rows cannot differ.
CSV_FIELDS: tuple[str, ...] = (
    "strategy",
    "scenario",
    "seed",
    "offered",
    "completed",
    "failed",
    "slo_violation_rate",
    "failure_rate",
    "malicious_share",
    "mean_latency_ms",
    "p95_latency_ms",
    "gini",
    "time_to_isolate_s",
)


def as_rows(results: Sequence[RunResult]) -> list[dict[str, Any]]:
    """Return one rounded row per run, with the fields in :data:`CSV_FIELDS`.

    Rounding happens here rather than at read time, so a row kept in memory and
    a row parsed back out of the CSV carry the same value. ``time_to_isolate_s``
    is ``''`` rather than ``0.0`` when nothing was isolated: no isolation and
    isolation at zero seconds are different facts.
    """
    return [
        {
            "strategy": r.strategy,
            "scenario": r.scenario,
            "seed": r.seed,
            "offered": r.offered,
            "completed": r.completed,
            "failed": r.failed,
            "slo_violation_rate": round(r.slo_violation_rate, 6),
            "failure_rate": round(r.failure_rate, 6),
            "malicious_share": round(r.malicious_share, 6),
            "mean_latency_ms": round(r.mean_latency_ms, 3),
            "p95_latency_ms": round(r.p95_latency_ms, 3),
            "gini": round(r.gini, 4),
            "time_to_isolate_s": (
                "" if r.time_to_isolate_s is None else round(r.time_to_isolate_s, 3)
            ),
        }
        for r in results
    ]


def write_csv(results: Sequence[RunResult], path: str | PathLike[str]) -> None:
    """Write :func:`as_rows` to ``path`` as CSV with a header row."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        writer.writerows(as_rows(results))
