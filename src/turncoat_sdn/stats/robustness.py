"""Cross-scenario robustness rankings for load-balancing strategies."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from math import isfinite
from numbers import Real
from statistics import mean, pstdev
from typing import Any

from turncoat_sdn.stats.replicates import RESULT_METRICS


def rank_strategies(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    scenarios: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Rank strategies across scenarios using their mean per-scenario metric.

    Each strategy is first averaged across its available seeds within a
    scenario. Strategies are ranked within each scenario, respecting the
    direction in RESULT_METRICS. The overall rank is the mean of those ranks.

    Ties receive the average rank. Missing metric values are ignored. Every
    requested scenario must contain at least one valid value for every
    strategy being ranked.

    Returns a dictionary containing the metric, scenario rankings and overall
    rankings sorted from best to worst.
    """
    if metric not in RESULT_METRICS:
        raise ValueError(f"unknown metric: {metric!r}")
    if not rows:
        raise ValueError("rows must not be empty")

    requested = (
        list(scenarios)
        if scenarios is not None
        else sorted({str(row.get("scenario", "")) for row in rows})
    )
    if not requested or any(not isinstance(s, str) or not s.strip() for s in requested):
        raise ValueError("scenarios must contain non-empty names")
    if len(set(requested)) != len(requested):
        raise ValueError("scenarios must not contain duplicates")

    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    strategies: set[str] = set()

    for row in rows:
        strategy = row.get("strategy")
        scenario = row.get("scenario")
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError("each row must have a non-empty strategy")
        if not isinstance(scenario, str) or not scenario.strip():
            raise ValueError("each row must have a non-empty scenario")
        if scenario not in requested:
            continue

        strategies.add(strategy)
        value = row.get(metric)
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            raise ValueError(f"metric {metric!r} must contain finite numbers or None")
        grouped[(strategy, scenario)].append(float(value))

    if len(strategies) < 2:
        raise ValueError("at least two strategies are required")

    means: dict[str, dict[str, float]] = {}
    for scenario in requested:
        present = {
            strategy: mean(grouped[(strategy, scenario)])
            for strategy in strategies
            if grouped[(strategy, scenario)]
        }
        if set(present) != strategies:
            missing = sorted(strategies - set(present))
            raise ValueError(
                f"scenario {scenario!r} has no valid {metric!r} values for: " + ", ".join(missing)
            )
        means[scenario] = present

    higher_is_better = not RESULT_METRICS[metric]
    scenario_rankings: list[dict[str, Any]] = []
    ranks_by_strategy: dict[str, list[float]] = {strategy: [] for strategy in strategies}

    for scenario in requested:
        ordered = sorted(
            means[scenario],
            key=lambda name: means[scenario][name],
            reverse=higher_is_better,
        )
        ranks: dict[str, float] = {}
        i = 0
        while i < len(ordered):
            j = i + 1
            while j < len(ordered) and means[scenario][ordered[j]] == means[scenario][ordered[i]]:
                j += 1
            rank = ((i + 1) + j) / 2
            for strategy in ordered[i:j]:
                ranks[strategy] = rank
                ranks_by_strategy[strategy].append(rank)
            i = j

        scenario_rankings.append(
            {
                "scenario": scenario,
                "metric_means": dict(sorted(means[scenario].items())),
                "ranks": dict(sorted(ranks.items())),
            }
        )

    overall = [
        {
            "strategy": strategy,
            "average_rank": mean(ranks),
            "rank_stddev": pstdev(ranks),
            "scenarios_ranked": len(ranks),
        }
        for strategy, ranks in ranks_by_strategy.items()
    ]
    overall.sort(key=lambda item: (item["average_rank"], item["strategy"]))

    return {
        "metric": metric,
        "higher_is_better": higher_is_better,
        "scenarios": requested,
        "scenario_rankings": scenario_rankings,
        "overall_rankings": overall,
    }
