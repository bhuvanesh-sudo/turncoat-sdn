"""Statistics over many runs: descriptive summaries, bootstrap confidence
intervals, the replicate results file, paired Wilcoxon signed-rank tests,
and Holm correction for multiple comparisons.

Owner: arv.
Lands in: v0.3 (descriptive summaries), v0.4.
Ported from the final-year project:
evaluation/stats.py.

``turncoat replicate`` writes one row per run with
:func:`~turncoat_sdn.stats.replicates.write_results`, and every metric's mean
comes with a percentile-bootstrap interval from
:func:`~turncoat_sdn.stats.bootstrap.bootstrap_ci`::

    from turncoat_sdn.stats import RESULT_METRICS, bootstrap_metrics, read_results

    rows = read_results("results.csv")
    for group in bootstrap_metrics(rows, list(RESULT_METRICS)):
        print(group["strategy"], group["scenario"], group["slo_violation_rate"].format())

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.stats.bootstrap import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    ConfidenceInterval,
    bootstrap_ci,
    bootstrap_metrics,
)
from turncoat_sdn.stats.replicates import (
    RESULT_METRICS,
    RESULTS_FIELDS,
    RESULTS_VERSION,
    detection_columns,
    read_results,
    results_row,
    write_results,
)

__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_RESAMPLES",
    "RESULTS_FIELDS",
    "RESULTS_VERSION",
    "RESULT_METRICS",
    "ConfidenceInterval",
    "bootstrap_ci",
    "bootstrap_metrics",
    "detection_columns",
    "read_results",
    "results_row",
    "write_results",
    "PairedComparison",
    "holm_adjust",
    "paired_wilcoxon",
    "AdjustedComparison",
    "ComparisonReport",
    "compare_strategies",
]

from turncoat_sdn.stats.compare import (
    AdjustedComparison,
    ComparisonReport,
    compare_strategies,
)
from turncoat_sdn.stats.paired import (
    PairedComparison,
    holm_adjust,
    paired_wilcoxon,
)
