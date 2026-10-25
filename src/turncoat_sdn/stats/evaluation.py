"""Combined descriptive and paired statistical evaluation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from turncoat_sdn.stats.bootstrap import DEFAULT_CONFIDENCE, DEFAULT_RESAMPLES
from turncoat_sdn.stats.compare import compare_strategies
from turncoat_sdn.stats.descriptive import summarize_metrics
from turncoat_sdn.stats.replicates import RESULT_METRICS


def build_evaluation_report(
    rows: list[dict[str, Any]],
    *,
    strategies: tuple[str, ...],
    scenarios: tuple[str, ...],
    metrics: tuple[str, ...],
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    bootstrap_seed: int = 0,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Combine per-group summaries, bootstrap intervals, and paired tests."""
    if not metrics:
        raise ValueError("at least one metric is required")

    unknown = set(metrics) - set(RESULT_METRICS)
    if unknown:
        raise ValueError(f"unknown metrics: {', '.join(sorted(unknown))}")

    selected = [
        row
        for row in rows
        if row.get("strategy") in strategies and row.get("scenario") in scenarios
    ]

    summaries = summarize_metrics(
        selected,
        group_by=("strategy", "scenario"),
        metrics=metrics,
        confidence=confidence,
        resamples=resamples,
        seed=bootstrap_seed,
    )
    comparisons = compare_strategies(
        rows,
        strategies=strategies,
        scenarios=scenarios,
        metrics=metrics,
        alpha=alpha,
        alternative=alternative,
    )

    # Attach a paired-bootstrap interval to each tested mean difference.
    from turncoat_sdn.stats.bootstrap import paired_bootstrap_ci

    comparison_rows = []
    for item in comparisons.comparisons:
        comparison = item.comparison
        interval = paired_bootstrap_ci(
            rows,
            comparison.strategy_a,
            comparison.strategy_b,
            comparison.scenario,
            comparison.metric,
            confidence=confidence,
            resamples=resamples,
            seed=bootstrap_seed,
        )
        comparison_rows.append(
            {
                **asdict(comparison),
                "adjusted_p_value": item.adjusted_p_value,
                "significant": item.significant,
                "paired_ci_low": interval.low,
                "paired_ci_high": interval.high,
                "paired_ci_confidence": confidence,
            }
        )

    return {
        "schema_version": 1,
        "configuration": {
            "strategies": list(strategies),
            "scenarios": list(scenarios),
            "metrics": list(metrics),
            "confidence": confidence,
            "resamples": resamples,
            "bootstrap_seed": bootstrap_seed,
            "alpha": alpha,
            "alternative": alternative,
            "correction": "Holm",
        },
        "summaries": summaries,
        "comparisons": comparison_rows,
        "n_comparisons": comparisons.n_comparisons,
        "n_significant": comparisons.n_significant,
    }
