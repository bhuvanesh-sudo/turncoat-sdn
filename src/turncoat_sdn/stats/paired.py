"""Paired strategy comparisons and multiple-testing correction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any, Literal

from scipy.stats import wilcoxon

Alternative = Literal["two-sided", "less", "greater"]


@dataclass(frozen=True)
class PairedComparison:
    """Wilcoxon signed-rank result for two strategies on matched runs."""

    strategy_a: str
    strategy_b: str
    scenario: str
    metric: str
    n_pairs: int
    n_missing_pairs: int
    statistic: float
    p_value: float
    mean_difference: float
    median_difference: float
    alternative: Alternative


def _metric_value(row: Mapping[str, Any], metric: str) -> float | None:
    value = row.get(metric)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"metric {metric!r} must be numeric or missing, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"metric {metric!r} must be finite, got {value!r}")
    return number


def paired_wilcoxon(
    rows: Sequence[Mapping[str, Any]],
    strategy_a: str,
    strategy_b: str,
    scenario: str,
    metric: str,
    *,
    alternative: Alternative = "two-sided",
) -> PairedComparison:
    """Compare strategies using rows paired by scenario and seed.

    Differences are strategy_a minus strategy_b. Each strategy must have
    exactly one row for every seed in the requested scenario. If either
    metric is missing for a seed, that pair is excluded.
    """
    labels = (strategy_a, strategy_b, scenario, metric)
    if not all(isinstance(value, str) and value.strip() for value in labels):
        raise ValueError("strategy names, scenario, and metric must be non-empty strings")
    if strategy_a == strategy_b:
        raise ValueError("strategies must be different")
    if alternative not in ("two-sided", "less", "greater"):
        raise ValueError(f"unsupported alternative {alternative!r}")

    selected: dict[str, dict[int, Mapping[str, Any]]] = {
        strategy_a: {},
        strategy_b: {},
    }
    for row in rows:
        missing = [key for key in ("strategy", "scenario", "seed") if key not in row]
        if missing:
            raise ValueError(f"row missing required keys: {', '.join(missing)}")
        if row["scenario"] != scenario or row["strategy"] not in selected:
            continue
        seed = row["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {seed!r}")
        strategy_rows = selected[row["strategy"]]
        if seed in strategy_rows:
            raise ValueError(
                f"duplicate row for strategy {row['strategy']!r}, "
                f"scenario {scenario!r}, seed {seed}"
            )
        strategy_rows[seed] = row

    seeds_a = set(selected[strategy_a])
    seeds_b = set(selected[strategy_b])
    if seeds_a != seeds_b:
        only_a = sorted(seeds_a - seeds_b)
        only_b = sorted(seeds_b - seeds_a)
        raise ValueError(
            "strategies must have matching seeds for the scenario; "
            f"only {strategy_a!r}: {only_a}; only {strategy_b!r}: {only_b}"
        )
    if not seeds_a:
        raise ValueError(
            f"no rows found for {strategy_a!r} and {strategy_b!r} in scenario {scenario!r}"
        )

    differences: list[float] = []
    missing_pairs = 0
    for seed in sorted(seeds_a):
        value_a = _metric_value(selected[strategy_a][seed], metric)
        value_b = _metric_value(selected[strategy_b][seed], metric)
        if value_a is None or value_b is None:
            missing_pairs += 1
            continue
        differences.append(value_a - value_b)

    if not differences:
        raise ValueError(f"no complete pairs with metric {metric!r}")

    mean_difference = math.fsum(differences) / len(differences)
    ordered = sorted(differences)
    middle = len(ordered) // 2
    median_difference = (
        ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    )
    if all(value == 0 for value in differences):
        statistic, p_value = 0.0, 1.0
    else:
        result = wilcoxon(differences, alternative=alternative, method="auto")
        statistic, p_value = float(result.statistic), float(result.pvalue)

    return PairedComparison(
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        scenario=scenario,
        metric=metric,
        n_pairs=len(differences),
        n_missing_pairs=missing_pairs,
        statistic=statistic,
        p_value=p_value,
        mean_difference=mean_difference,
        median_difference=median_difference,
        alternative=alternative,
    )


def holm_adjust(p_values: Sequence[float]) -> tuple[float, ...]:
    """Return Holm-Bonferroni adjusted p-values in original input order."""
    checked: list[float] = []
    for index, value in enumerate(p_values):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"p-value at index {index} must be numeric, got {value!r}")
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"p-value at index {index} must be finite and in [0, 1]")
        checked.append(number)

    count = len(checked)
    if count == 0:
        return ()
    order = sorted(range(count), key=checked.__getitem__)
    adjusted = [0.0] * count
    running_max = 0.0
    for rank, original_index in enumerate(order):
        candidate = (count - rank) * checked[original_index]
        running_max = max(running_max, candidate)
        adjusted[original_index] = min(1.0, running_max)
    return tuple(adjusted)
