"""The turncoat evaluate command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.replicate import _names
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.sim import SCENARIOS
from turncoat_sdn.stats import RESULT_METRICS, read_results
from turncoat_sdn.stats.bootstrap import DEFAULT_CONFIDENCE, DEFAULT_RESAMPLES
from turncoat_sdn.stats.evaluation import build_evaluation_report


def _level(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError("level must be strictly between 0 and 1")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("value must be an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return value


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        "evaluate",
        help="summarize runs and compare strategies in one JSON report",
    )
    parser.add_argument("results", metavar="RESULTS.csv")
    parser.add_argument(
        "--strategies",
        type=_names(list(STRATEGIES), "strategy"),
        default=list(STRATEGIES),
        metavar="LIST",
    )
    parser.add_argument(
        "--scenarios",
        type=_names(list(SCENARIOS), "scenario"),
        default=list(SCENARIOS),
        metavar="LIST",
    )
    parser.add_argument(
        "--metrics",
        type=_names(list(RESULT_METRICS), "metric"),
        default=list(RESULT_METRICS),
        metavar="LIST",
    )
    parser.add_argument("--alpha", type=_level, default=0.05)
    parser.add_argument("--confidence", type=_level, default=DEFAULT_CONFIDENCE)
    parser.add_argument("--resamples", type=_positive_int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--alternative", choices=("two-sided", "less", "greater"), default="two-sided"
    )
    parser.add_argument("-o", "--output", default="evaluation.json", metavar="PATH")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    try:
        rows = read_results(args.results)
    except OSError as exc:
        print(f"turncoat evaluate: cannot read input: {exc}")
        return EXIT_UNREADABLE
    except (UnicodeError, ValueError) as exc:
        print(f"turncoat evaluate: invalid results file: {exc}")
        return EXIT_FAILED

    try:
        report = build_evaluation_report(
            rows,
            strategies=tuple(args.strategies),
            scenarios=tuple(args.scenarios),
            metrics=tuple(args.metrics),
            confidence=args.confidence,
            resamples=args.resamples,
            bootstrap_seed=args.seed,
            alpha=args.alpha,
            alternative=args.alternative,
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\\n")
    except OSError as exc:
        print(f"turncoat evaluate: cannot write output: {exc}")
        return EXIT_UNREADABLE
    except (TypeError, ValueError) as exc:
        print(f"turncoat evaluate: evaluation failed: {exc}")
        return EXIT_FAILED

    if not args.quiet:
        print(
            f"Wrote {args.output}: {report['n_comparisons']} comparisons, "
            f"{report['n_significant']} significant."
        )
    return EXIT_OK
