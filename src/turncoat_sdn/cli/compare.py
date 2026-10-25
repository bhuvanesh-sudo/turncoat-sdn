"""``turncoat compare``: paired strategy comparisons from a results CSV.

Reads the results file ``turncoat replicate`` writes, pairs every two chosen
strategies run for run on matched seeds, and prints one table per scenario and
pair: for every metric, both strategies' means, the mean paired difference
with a paired bootstrap confidence interval, the Wilcoxon signed-rank p-value
and its Holm-adjusted value. The same comparisons are written to a CSV report.

Every test in the table is one Holm family. A metric no seed can measure for a
pair, such as time to isolate in a scenario with no attacker, is left out of
the family and listed under the table instead of stopping the command.

The statistics come from :mod:`turncoat_sdn.stats`; this module only chooses
what to compare and prints it.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Mapping, Sequence
from typing import Any

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.replicate import (
    METRIC_LABELS,
    _confidence,
    _names,
    _positive_int,
    format_interval,
)
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.sim import SCENARIOS
from turncoat_sdn.stats import (
    RESULT_METRICS,
    AdjustedComparison,
    ComparisonReport,
    ConfidenceInterval,
    holm_adjust,
    paired_wilcoxon,
    read_results,
    write_comparison_report,
)
from turncoat_sdn.stats.bootstrap import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    paired_bootstrap_ci,
)

DEFAULT_ALPHA = 0.05


def _alpha(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0.0 < value < 1.0:
        raise argparse.ArgumentTypeError(f"{text!r} must be strictly between 0 and 1")
    return value


def _measured(value: Any) -> bool:
    return value is not None and value != ""


def paired_values(
    rows: Sequence[Mapping[str, Any]],
    strategy_a: str,
    strategy_b: str,
    scenario: str,
    metric: str,
) -> tuple[list[float], list[float]]:
    """Both strategies' values of ``metric`` on every seed where both measured it.

    These are the pairs :func:`~turncoat_sdn.stats.paired_wilcoxon` tests,
    in seed order.
    """
    runs: dict[str, dict[int, Mapping[str, Any]]] = {strategy_a: {}, strategy_b: {}}
    for row in rows:
        if row.get("scenario") == scenario and row.get("strategy") in runs:
            runs[row["strategy"]][row["seed"]] = row
    a_values: list[float] = []
    b_values: list[float] = []
    for seed in sorted(runs[strategy_a].keys() & runs[strategy_b].keys()):
        a, b = runs[strategy_a][seed].get(metric), runs[strategy_b][seed].get(metric)
        if _measured(a) and _measured(b):
            a_values.append(float(a))
            b_values.append(float(b))
    return a_values, b_values


def build_report(
    rows: Sequence[Mapping[str, Any]],
    strategies: Sequence[str],
    scenarios: Sequence[str],
    metrics: Sequence[str],
    *,
    alpha: float = DEFAULT_ALPHA,
    alternative: str = "two-sided",
) -> tuple[ComparisonReport, list[tuple[str, str, str, str]]]:
    """:func:`~turncoat_sdn.stats.compare_strategies`, minus what cannot be measured.

    Compares every pair of ``strategies`` on every scenario and metric, in the
    same order and with the same Holm family as ``compare_strategies``. A
    (scenario, metric, pair) with no seed on which both strategies measured
    the metric cannot be tested; it is left out of the family and returned in
    the second list as ``(scenario, metric, strategy_a, strategy_b)``.

    Raises:
        ValueError: Fewer than two strategies, or a strategy has no runs in a
            scenario.
    """
    if len(strategies) < 2:
        raise ValueError("at least two strategies are required")
    available = {(row.get("strategy"), row.get("scenario")) for row in rows}
    for scenario in scenarios:
        for strategy in strategies:
            if (strategy, scenario) not in available:
                raise ValueError(f"no rows found for {strategy!r} in scenario {scenario!r}")

    tested = []
    skipped: list[tuple[str, str, str, str]] = []
    for scenario in scenarios:
        for metric in metrics:
            for index, strategy_a in enumerate(strategies):
                for strategy_b in strategies[index + 1 :]:
                    if not paired_values(rows, strategy_a, strategy_b, scenario, metric)[0]:
                        skipped.append((scenario, metric, strategy_a, strategy_b))
                        continue
                    tested.append(
                        paired_wilcoxon(
                            rows,
                            strategy_a=strategy_a,
                            strategy_b=strategy_b,
                            scenario=scenario,
                            metric=metric,
                            alternative=alternative,
                        )
                    )

    adjusted = holm_adjust([item.p_value for item in tested])
    report = ComparisonReport(
        comparisons=tuple(
            AdjustedComparison(comparison=item, adjusted_p_value=p, significant=p <= alpha)
            for item, p in zip(tested, adjusted, strict=True)
        ),
        alpha=alpha,
    )
    return report, skipped


def _p(value: float) -> str:
    return "<0.0001" if value < 0.0001 else f"{value:.4f}"


def _mean_text(values: Sequence[float], style: str) -> str:
    mean = math.fsum(values) / len(values)
    point = ConfidenceInterval(mean, mean, mean, len(values), DEFAULT_CONFIDENCE, 1)
    return format_interval(point, style).split(" [", 1)[0]


def _difference_text(interval: ConfidenceInterval, style: str) -> str:
    if interval.mean is None or interval.low is None or interval.high is None:
        return "n/a"
    scale, spec = (100.0, "+.2f") if style == "%" else (1.0, "+" + style)
    mean, low, high = (
        format(v * scale, spec) for v in (interval.mean, interval.low, interval.high)
    )
    return f"{mean} [{low}, {high}]"


def _better(item: AdjustedComparison) -> str:
    result = item.comparison
    if not item.significant or result.mean_difference == 0:
        return "-"
    lower_is_better = RESULT_METRICS.get(result.metric, True)
    a_is_lower = result.mean_difference < 0
    return result.strategy_a if a_is_lower == lower_is_better else result.strategy_b


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    lines = []
    for row in [header, *rows]:
        cells = [row[0].ljust(widths[0])]
        cells += [cell.rjust(width) for cell, width in zip(row[1:-1], widths[1:-1], strict=True)]
        cells.append(row[-1])
        lines.append("  " + "   ".join(cells).rstrip())
    return lines


def format_comparisons(
    report: ComparisonReport,
    rows: Sequence[Mapping[str, Any]],
    skipped: Sequence[tuple[str, str, str, str]] = (),
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> str:
    """The comparison table: one block per scenario and pair, one row per metric."""
    blocks: dict[tuple[str, str, str], list[AdjustedComparison]] = {}
    for item in report.comparisons:
        result = item.comparison
        blocks.setdefault((result.scenario, result.strategy_a, result.strategy_b), []).append(item)

    level = f"{confidence * 100:g}%"
    out: list[str] = []
    for (scenario, strategy_a, strategy_b), items in blocks.items():
        pairs = max(item.comparison.n_pairs for item in items)
        out.append(f"{scenario}: {strategy_a} vs {strategy_b}  ({pairs} paired seeds)")
        table = []
        for item in items:
            result = item.comparison
            label, style = METRIC_LABELS.get(result.metric, (result.metric, ".4g"))
            if result.n_pairs < pairs:
                label = f"{label}, {result.n_pairs} pairs"
            a_values, b_values = paired_values(
                rows, strategy_a, strategy_b, scenario, result.metric
            )
            interval = paired_bootstrap_ci(
                rows,
                strategy_a,
                strategy_b,
                scenario,
                result.metric,
                confidence=confidence,
                resamples=resamples,
                seed=seed,
            )
            table.append(
                [
                    label,
                    _mean_text(a_values, style),
                    _mean_text(b_values, style),
                    _difference_text(interval, style),
                    _p(result.p_value),
                    _p(item.adjusted_p_value),
                    _better(item),
                ]
            )
        header = ["", strategy_a, strategy_b, f"Difference [{level} CI]", "p", "Holm p", "Better"]
        out.extend(_table(header, table))
        out.append("")

    if skipped:
        out.append("Not compared, because no seed measured them for both strategies:")
        by_scenario: dict[str, list[str]] = {}
        for scenario, metric, _, _ in skipped:
            names = by_scenario.setdefault(scenario, [])
            if metric not in names:
                names.append(metric)
        for scenario, metric_names in by_scenario.items():
            out.append(f"  {scenario}: {', '.join(metric_names)}")
        out.append("")

    alternative = report.comparisons[0].comparison.alternative if report.comparisons else ""
    out.append("Difference: first strategy minus second on each seed, averaged, with a paired")
    out.append(f"  percentile bootstrap interval ({resamples:,} resamples, seed {seed}).")
    out.append(
        f"p: {alternative} Wilcoxon signed-rank test. "
        f"Holm p: adjusted across all {report.n_comparisons} tests above."
    )
    out.append(
        f"Better: the better strategy when Holm p <= {report.alpha:g}; "
        "lower is better except for attackers named."
    )
    return "\n".join(out)


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the compare subcommand."""
    parser = commands.add_parser(
        "compare",
        help="compare strategies using paired tests and Holm correction",
        description=(
            "Compare strategies on matched seeds using paired Wilcoxon tests, "
            "adjust p-values with Holm's method, print a table with a paired bootstrap "
            "interval for every difference, and export a CSV report."
        ),
        epilog="Exit status: 0 when compared, 1 when the results file is invalid or cannot "
        "be compared, 2 when a file cannot be read or written or an option is wrong.",
    )
    parser.add_argument("results", metavar="RESULTS.csv", help="replicate results CSV")
    parser.add_argument(
        "--strategies",
        type=_names(list(STRATEGIES), "strategy"),
        default=None,
        metavar="LIST",
        help="comma-separated strategies to compare (default: every one in the file)",
    )
    parser.add_argument(
        "--scenarios",
        type=_names(list(SCENARIOS), "scenario"),
        default=None,
        metavar="LIST",
        help="comma-separated scenarios (default: every one in the file)",
    )
    parser.add_argument(
        "--metrics",
        type=_names(list(RESULT_METRICS), "metric"),
        default=list(RESULT_METRICS),
        metavar="LIST",
        help="comma-separated metrics to compare (default: all)",
    )
    parser.add_argument(
        "--alpha",
        type=_alpha,
        default=DEFAULT_ALPHA,
        metavar="LEVEL",
        help=f"significance level (default: {DEFAULT_ALPHA:g})",
    )
    parser.add_argument(
        "--alternative",
        choices=("two-sided", "less", "greater"),
        default="two-sided",
        help="alternative hypothesis (default: two-sided)",
    )
    parser.add_argument(
        "--confidence",
        type=_confidence,
        default=DEFAULT_CONFIDENCE,
        metavar="LEVEL",
        help=f"coverage of the difference intervals (default: {DEFAULT_CONFIDENCE:g})",
    )
    parser.add_argument(
        "--resamples",
        type=_positive_int,
        default=DEFAULT_RESAMPLES,
        metavar="N",
        help=f"bootstrap resamples per interval (default: {DEFAULT_RESAMPLES:,})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="comparisons.csv",
        metavar="PATH",
        help="comparison report CSV (default: comparisons.csv)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print nothing unless something goes wrong",
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    """Read results, calculate comparisons, print the table and write the report."""
    try:
        rows = read_results(args.results)
    except OSError as exc:
        print(f"turncoat compare: cannot read {args.results}: {exc.strerror or exc}")
        return EXIT_UNREADABLE
    except (UnicodeError, ValueError) as exc:
        print(f"turncoat compare: invalid results file {args.results}: {exc}")
        return EXIT_FAILED

    # By default compare what the file holds, so a replicate run on a few
    # strategies or scenarios compares without naming them again.
    strategies = args.strategies or list(dict.fromkeys(row["strategy"] for row in rows))
    scenarios = args.scenarios or list(dict.fromkeys(row["scenario"] for row in rows))
    try:
        report, skipped = build_report(
            rows,
            strategies=strategies,
            scenarios=scenarios,
            metrics=args.metrics,
            alpha=args.alpha,
            alternative=args.alternative,
        )
    except (TypeError, ValueError) as exc:
        print(f"turncoat compare: cannot compare results: {exc}")
        return EXIT_FAILED
    if not report.comparisons:
        print("turncoat compare: cannot compare results: no metric was measured for any pair")
        return EXIT_FAILED

    try:
        count = write_comparison_report(report, args.output)
    except OSError as exc:
        print(f"turncoat compare: cannot write {args.output}: {exc.strerror or exc}")
        return EXIT_UNREADABLE

    if not args.quiet:
        print(
            format_comparisons(
                report,
                rows,
                skipped,
                confidence=args.confidence,
                resamples=args.resamples,
            )
        )
        print()
        print(
            f"Wrote {args.output} ({count} comparisons, "
            f"{report.n_significant} significant at alpha={report.alpha:g})"
        )
    return EXIT_OK


__all__ = ["build_report", "format_comparisons", "paired_values"]
