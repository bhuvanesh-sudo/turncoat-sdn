"""Percentile-bootstrap confidence intervals for a metric's mean over runs.

A benchmark result is a mean over seeds, and a mean without its uncertainty
cannot be compared with another. This module puts a 95% interval on every
metric: resample the runs with replacement, take the mean of each resample,
and read the interval off the middle 95% of those means (the percentile
bootstrap). It makes no assumption about the shape of the metric's
distribution, which matters for rates that pile up at 0 or 1.

Resampling is seeded, so the same runs give the same interval every time. The
same seed draws the same resample indices for every group of the same size,
so strategies run on the same seeds are resampled run for run: the intervals
are paired in the same way the runs are.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Resamples per interval. 10,000 puts the Monte Carlo error on a 95% bound
#: well under the bound's own sampling error at 30 runs.
DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_SEED = 0


@dataclass(frozen=True)
class ConfidenceInterval:
    """A metric's mean over runs, with a bootstrap interval around it.

    ``mean``, ``low`` and ``high`` are ``None`` when there were no runs to
    average. With one run, or runs that all agree, the interval is the mean.
    """

    mean: float | None
    low: float | None
    high: float | None
    n: int
    confidence: float
    resamples: int

    def format(self, spec: str = ".4g") -> str:
        """``mean [low, high]`` with each number formatted by ``spec``, or ``n/a``."""
        if self.mean is None or self.low is None or self.high is None:
            return "n/a"
        return f"{self.mean:{spec}} [{self.low:{spec}}, {self.high:{spec}}]"


def _observations(values: Iterable[Any]) -> list[float]:
    """The numeric values, skipping ``None`` and ``''`` (a blank CSV cell)."""
    observations: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"observations must be numeric, got {value!r}")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"observations must be finite, got {value!r}")
        observations.append(number)
    return observations


def _check(confidence: float, resamples: int) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence!r}")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError(f"resamples must be a whole number of at least 1, got {resamples!r}")


def bootstrap_ci(
    values: Iterable[Any],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> ConfidenceInterval:
    """Mean of ``values`` with a percentile-bootstrap confidence interval.

    Args:
        values: One observation per run. ``None`` and ``''`` are skipped, so a
            metric a run could not measure (no attacker to detect) does not
            count as zero.
        confidence: Coverage of the interval, 0.95 for 95%.
        resamples: How many bootstrap resamples to draw.
        seed: Seeds the resampling, so the interval is reproducible.
    """
    _check(confidence, resamples)
    observations = _observations(values)
    n = len(observations)
    if n == 0:
        return ConfidenceInterval(None, None, None, 0, confidence, resamples)

    mean = math.fsum(observations) / n
    if n == 1 or min(observations) == max(observations):
        return ConfidenceInterval(mean, mean, mean, n, confidence, resamples)

    data = np.asarray(observations, dtype=float)
    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, n, size=(resamples, n))].mean(axis=1)
    alpha = 1.0 - confidence
    low, high = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return ConfidenceInterval(mean, float(low), float(high), n, confidence, resamples)


def paired_bootstrap_ci(
    rows: Sequence[Mapping[str, Any]],
    strategy_a: str,
    strategy_b: str,
    scenario: str,
    metric: str,
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> ConfidenceInterval:
    """Bootstrap the mean difference using matched strategy runs.

    Rows are paired by seed. Each bootstrap draw resamples the paired
    differences, preserving the dependence between strategies.
    Differences are strategy_a minus strategy_b.
    """
    from turncoat_sdn.stats.paired import paired_wilcoxon

    _check(confidence, resamples)

    # Reuse the established validation for labels, seeds, duplicate rows,
    # matching seed sets, and complete metric pairs.
    paired_wilcoxon(rows, strategy_a, strategy_b, scenario, metric)

    selected: dict[str, dict[int, Mapping[str, Any]]] = {
        strategy_a: {},
        strategy_b: {},
    }
    for row in rows:
        if row.get("scenario") != scenario or row.get("strategy") not in selected:
            continue
        selected[row["strategy"]][row["seed"]] = row

    differences: list[float] = []
    for run_seed in sorted(selected[strategy_a]):
        value_a = selected[strategy_a][run_seed].get(metric)
        value_b = selected[strategy_b][run_seed].get(metric)
        if value_a is None or value_a == "" or value_b is None or value_b == "":
            continue
        differences.append(float(value_a) - float(value_b))

    data = np.asarray(differences, dtype=float)
    mean = math.fsum(differences) / len(differences)
    if len(differences) == 1 or np.all(data == data[0]):
        return ConfidenceInterval(mean, mean, mean, len(differences), confidence, resamples)

    rng = np.random.default_rng(seed)
    means = data[rng.integers(0, len(data), size=(resamples, len(data)))].mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return ConfidenceInterval(
        mean, float(low), float(high), len(differences), confidence, resamples
    )


def bootstrap_metrics(
    rows: Iterable[Mapping[str, Any]],
    metrics: Sequence[str],
    *,
    group_by: Sequence[str] = ("strategy", "scenario"),
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """An interval for every metric in every group of runs.

    Args:
        rows: One mapping per run, such as the rows of a results CSV.
        metrics: The columns to put intervals on.
        group_by: The columns that define a group. Groups come back in the
            order they first appear in ``rows``.

    Returns:
        One dict per group: the ``group_by`` values, ``runs``, and a
        :class:`ConfidenceInterval` under each metric's name.
    """
    _check(confidence, resamples)
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        missing = [key for key in group_by if key not in row]
        if missing:
            raise ValueError(f"row missing grouping keys: {', '.join(missing)}")
        groups.setdefault(tuple(row[key] for key in group_by), []).append(row)

    output: list[dict[str, Any]] = []
    for key, group in groups.items():
        entry: dict[str, Any] = dict(zip(group_by, key, strict=True))
        entry["runs"] = len(group)
        for metric in metrics:
            entry[metric] = bootstrap_ci(
                (row.get(metric) for row in group),
                confidence=confidence,
                resamples=resamples,
                seed=seed,
            )
        output.append(entry)
    return output
