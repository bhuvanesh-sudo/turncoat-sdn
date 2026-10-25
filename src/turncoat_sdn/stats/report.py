"""CSV export for multi-strategy comparison reports."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from turncoat_sdn.stats.compare import ComparisonReport

COMPARISON_FIELDS: tuple[str, ...] = (
    "strategy_a",
    "strategy_b",
    "scenario",
    "metric",
    "n_pairs",
    "n_missing_pairs",
    "statistic",
    "p_value",
    "adjusted_p_value",
    "mean_difference",
    "median_difference",
    "alternative",
    "alpha",
    "significant",
)


def comparison_rows(report: ComparisonReport) -> list[dict[str, object]]:
    """Convert a comparison report to ordered, CSV-ready records."""
    rows: list[dict[str, object]] = []
    for item in report.comparisons:
        result = item.comparison
        rows.append(
            {
                "strategy_a": result.strategy_a,
                "strategy_b": result.strategy_b,
                "scenario": result.scenario,
                "metric": result.metric,
                "n_pairs": result.n_pairs,
                "n_missing_pairs": result.n_missing_pairs,
                "statistic": result.statistic,
                "p_value": result.p_value,
                "adjusted_p_value": item.adjusted_p_value,
                "mean_difference": result.mean_difference,
                "median_difference": result.median_difference,
                "alternative": result.alternative,
                "alpha": report.alpha,
                "significant": item.significant,
            }
        )
    return rows


def write_comparison_report(
    report: ComparisonReport,
    path: str | os.PathLike[str],
) -> int:
    """Write a comparison report to CSV and return the number of rows written.

    The file has a stable column order. Parent directories are created when
    needed, and the header is written even if the report contains no results.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    rows = comparison_rows(report)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(COMPARISON_FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)
