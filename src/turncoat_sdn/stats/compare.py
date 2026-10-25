"""Multi-strategy paired comparisons with family-wise error correction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Any

from turncoat_sdn.stats.paired import (
    Alternative,
    PairedComparison,
    holm_adjust,
    paired_wilcoxon,
)


@dataclass(frozen=True)
class AdjustedComparison:
    """A paired comparison with its multiple-testing adjustment."""

    comparison: PairedComparison
    adjusted_p_value: float
    significant: bool


@dataclass(frozen=True)
class ComparisonReport:
    """Results for one explicitly defined family of comparisons."""

    comparisons: tuple[AdjustedComparison, ...]
    alpha: float

    @property
    def n_comparisons(self) -> int:
        """Number of statistical tests included in this report."""
        return len(self.comparisons)

    @property
    def n_significant(self) -> int:
        """Number of comparisons significant after adjustment."""
        return sum(item.significant for item in self.comparisons)


def compare_strategies(
    rows: Sequence[Mapping[str, Any]],
    strategies: Sequence[str],
    scenarios: Sequence[str],
    metrics: Sequence[str],
    *,
    alpha: float = 0.05,
    alternative: Alternative = "two-sided",
) -> ComparisonReport:
    """Compare every strategy pair for each scenario and metric.

    All comparisons produced by this call belong to one Holm correction
    family. Differences are calculated as the first strategy minus the
    second strategy, following :func:`paired_wilcoxon`.

    Every requested comparison must have matched seed sets. The function
    raises if any requested comparison cannot be calculated.
    """
    if isinstance(alpha, bool) or not isinstance(alpha, Real):
        raise TypeError("alpha must be numeric")
    alpha = float(alpha)
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be finite and strictly between 0 and 1")

    for label, values in (
        ("strategies", strategies),
        ("scenarios", scenarios),
        ("metrics", metrics),
    ):
        if isinstance(values, (str, bytes)):
            raise TypeError(f"{label} must be a sequence of strings, not a string")
        if not values:
            raise ValueError(f"{label} must not be empty")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"{label} must contain non-empty strings")
        if len(set(values)) != len(values):
            raise ValueError(f"{label} must not contain duplicates")

    if len(strategies) < 2:
        raise ValueError("at least two strategies are required")
    if alternative not in ("two-sided", "less", "greater"):
        raise ValueError(f"unsupported alternative {alternative!r}")

    available = {(row.get("strategy"), row.get("scenario")) for row in rows}
    for scenario in scenarios:
        for strategy in strategies:
            if (strategy, scenario) not in available:
                raise ValueError(f"no rows found for {strategy!r} in scenario {scenario!r}")

    raw: list[PairedComparison] = []
    for scenario in scenarios:
        for metric in metrics:
            for index, strategy_a in enumerate(strategies):
                for strategy_b in strategies[index + 1 :]:
                    raw.append(
                        paired_wilcoxon(
                            rows,
                            strategy_a=strategy_a,
                            strategy_b=strategy_b,
                            scenario=scenario,
                            metric=metric,
                            alternative=alternative,
                        )
                    )

    adjusted_values = holm_adjust([item.p_value for item in raw])
    adjusted = tuple(
        AdjustedComparison(
            comparison=comparison,
            adjusted_p_value=adjusted_p_value,
            significant=adjusted_p_value <= alpha,
        )
        for comparison, adjusted_p_value in zip(raw, adjusted_values, strict=True)
    )
    return ComparisonReport(comparisons=adjusted, alpha=alpha)
