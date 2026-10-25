"""``turncoat compare``: paired strategy comparisons from a results CSV."""

from __future__ import annotations

import argparse

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.replicate import _names
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.sim import SCENARIOS
from turncoat_sdn.stats import (
    RESULT_METRICS,
    compare_strategies,
    read_results,
    write_comparison_report,
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


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the compare subcommand."""
    parser = commands.add_parser(
        "compare",
        help="compare strategies using paired tests and Holm correction",
        description=(
            "Compare strategies on matched seeds using paired Wilcoxon tests, "
            "adjust p-values with Holm's method, and export a CSV report."
        ),
    )
    parser.add_argument("results", metavar="RESULTS.csv", help="replicate results CSV")
    parser.add_argument(
        "--strategies",
        type=_names(list(STRATEGIES), "strategy"),
        default=list(STRATEGIES),
        metavar="LIST",
        help="comma-separated strategies to compare (default: all)",
    )
    parser.add_argument(
        "--scenarios",
        type=_names(list(SCENARIOS), "scenario"),
        default=list(SCENARIOS),
        metavar="LIST",
        help="comma-separated scenarios (default: all)",
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
    """Read results, calculate comparisons, and write the report."""
    try:
        rows = read_results(args.results)
    except OSError as exc:
        print(f"turncoat compare: cannot read {args.results}: {exc.strerror or exc}")
        return EXIT_UNREADABLE
    except (UnicodeError, ValueError) as exc:
        print(f"turncoat compare: invalid results file {args.results}: {exc}")
        return EXIT_FAILED

    try:
        report = compare_strategies(
            rows,
            strategies=args.strategies,
            scenarios=args.scenarios,
            metrics=args.metrics,
            alpha=args.alpha,
            alternative=args.alternative,
        )
    except (TypeError, ValueError) as exc:
        print(f"turncoat compare: cannot compare results: {exc}")
        return EXIT_FAILED

    try:
        count = write_comparison_report(report, args.output)
    except OSError as exc:
        print(f"turncoat compare: cannot write {args.output}: {exc.strerror or exc}")
        return EXIT_UNREADABLE

    if not args.quiet:
        print(
            f"Compared {len(args.strategies)} strategies across "
            f"{len(args.scenarios)} scenarios and {len(args.metrics)} metrics."
        )
        print(
            f"Wrote {args.output} ({count} comparisons, "
            f"{report.n_significant} significant at alpha={report.alpha:g})"
        )
    return EXIT_OK
