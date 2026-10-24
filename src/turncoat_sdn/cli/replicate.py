"""``turncoat replicate``: many seeded runs, one results CSV, a mean and CI per metric.

Runs every chosen strategy on every chosen scenario over the same seeds,
scores each run's recording, and writes one row per run to the results file
(:mod:`turncoat_sdn.stats.replicates`). It then prints every metric's mean for
each strategy and scenario with a percentile-bootstrap 95% confidence interval
(:mod:`turncoat_sdn.stats.bootstrap`).

Each run gets the same controller view as ``turncoat run``: the real trust
calculator and the Sybil latency tell. Recordings are kept in memory and
scored there, so nothing is written but the results.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from turncoat_sdn.cli.common import EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.run import _non_negative_float, _non_negative_int, _positive_float
from turncoat_sdn.events import EventList
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import SCENARIOS, SimConfig, as_rows, simulate
from turncoat_sdn.stats.bootstrap import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    ConfidenceInterval,
    bootstrap_metrics,
)
from turncoat_sdn.stats.replicates import RESULT_METRICS, RESULTS_VERSION, results_row
from turncoat_sdn.stats.replicates import write_results as write_results_csv
from turncoat_sdn.trust import SimTrustModel, latency_tell

DEFAULT_OUTPUT = "results.csv"
DEFAULT_SEEDS = 30
DEFAULT_FIRST_SEED = 1

#: How each metric is labelled and printed: ``%`` for a rate shown as a
#: percentage, otherwise a format spec for the number as it is.
METRIC_LABELS: dict[str, tuple[str, str]] = {
    "slo_violation_rate": ("SLO violations (%)", "%"),
    "failure_rate": ("Failed (%)", "%"),
    "malicious_share": ("Routed to attackers (%)", "%"),
    "mean_latency_ms": ("Mean latency (ms)", ".1f"),
    "p95_latency_ms": ("p95 latency (ms)", ".1f"),
    "gini": ("Load Gini", ".3f"),
    "time_to_isolate_s": ("Time to isolate (s)", ".1f"),
    "detection_rate": ("Attackers named (%)", "%"),
    "mean_detection_latency_s": ("Detection latency (s)", ".1f"),
    "false_positive_rate": ("Honest mislabelled (%)", "%"),
}

SUMMARY_FIELDS = (
    "strategy",
    "scenario",
    "metric",
    "runs",
    "n",
    "mean",
    "ci_low",
    "ci_high",
    "confidence",
    "resamples",
)


def replicate_rows(
    *,
    strategies: Sequence[str],
    scenarios: Sequence[str],
    seeds: Sequence[int],
    config: SimConfig | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Run and score every strategy on every scenario and seed; one results row per run.

    Rows come back ordered by scenario, then seed, then strategy, as
    :func:`turncoat_sdn.sim.run_paired` orders its results. ``progress`` is
    called with (runs done, runs in total) after each run.
    """
    for name in strategies:
        if name not in STRATEGIES:
            raise ValueError(f"unknown strategy {name!r}; expected one of {list(STRATEGIES)}")
    for name in scenarios:
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario {name!r}; expected one of {list(SCENARIOS)}")

    total = len(strategies) * len(scenarios) * len(seeds)
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        for seed in seeds:
            for strategy in strategies:
                recording = EventList(
                    backend="sim", seed=seed, strategy=strategy, scenario=scenario
                )
                run = simulate(
                    STRATEGIES[strategy],
                    scenario,
                    seed,
                    config=config,
                    trust=SimTrustModel,
                    latency_tell=latency_tell,
                    name=strategy,
                    recorder=recording,
                )
                rows.append(results_row(as_rows([run])[0], score_run(recording.events)))
                if progress is not None:
                    progress(len(rows), total)
    return rows


def format_interval(interval: ConfidenceInterval, style: str) -> str:
    """``mean [low, high]``, as a percentage when ``style`` is ``%``."""
    if interval.mean is None or interval.low is None or interval.high is None:
        return "n/a"
    if style == "%":
        mean, low, high = (100 * v for v in (interval.mean, interval.low, interval.high))
        return f"{mean:.2f} [{low:.2f}, {high:.2f}]"
    return f"{interval.mean:{style}} [{interval.low:{style}}, {interval.high:{style}}]"


def format_summary(
    groups: Sequence[dict[str, Any]], strategies: Sequence[str], scenarios: Sequence[str]
) -> str:
    """One table per scenario: metrics down the side, strategies across."""
    lines: list[str] = []
    by_key = {(g["strategy"], g["scenario"]): g for g in groups}
    label_width = max(len(label) for label, _ in METRIC_LABELS.values())
    for scenario in scenarios:
        cells: dict[str, list[str]] = {}
        for strategy in strategies:
            group = by_key[(strategy, scenario)]
            cells[strategy] = [
                format_interval(group[metric], style)
                for metric, (_, style) in METRIC_LABELS.items()
            ]
        widths = {
            strategy: max(len(strategy), *(len(c) for c in cells[strategy]))
            for strategy in strategies
        }
        runs = by_key[(strategies[0], scenario)]["runs"]
        lines.append(f"{scenario}  ({runs} seeds per strategy)")
        lines.append(
            "  " + "".ljust(label_width) + "".join(f"  {s:>{widths[s]}}" for s in strategies)
        )
        for i, (label, _) in enumerate(METRIC_LABELS.values()):
            lines.append(
                "  "
                + label.ljust(label_width)
                + "".join(f"  {cells[s][i]:>{widths[s]}}" for s in strategies)
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def write_summary(groups: Sequence[dict[str, Any]], path: str | os.PathLike[str]) -> None:
    """Write every interval as a long-format CSV, one row per strategy, scenario and metric."""
    folder = os.path.dirname(os.fspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SUMMARY_FIELDS))
        writer.writeheader()
        for group in groups:
            for metric in RESULT_METRICS:
                interval: ConfidenceInterval = group[metric]
                writer.writerow(
                    {
                        "strategy": group["strategy"],
                        "scenario": group["scenario"],
                        "metric": metric,
                        "runs": group["runs"],
                        "n": interval.n,
                        "mean": "" if interval.mean is None else round(interval.mean, 6),
                        "ci_low": "" if interval.low is None else round(interval.low, 6),
                        "ci_high": "" if interval.high is None else round(interval.high, 6),
                        "confidence": interval.confidence,
                        "resamples": interval.resamples,
                    }
                )


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _names(choices: Sequence[str], what: str) -> Callable[[str], list[str]]:
    def parse(text: str) -> list[str]:
        names = [name.strip() for name in text.split(",") if name.strip()]
        unknown = [name for name in names if name not in choices]
        if not names:
            raise argparse.ArgumentTypeError(f"give at least one {what}")
        if unknown:
            raise argparse.ArgumentTypeError(
                f"unknown {what} {', '.join(unknown)}; choose from {', '.join(choices)}"
            )
        return list(dict.fromkeys(names))

    return parse


def _positive_int(text: str) -> int:
    value = _non_negative_int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} must be 1 or more")
    return value


def _confidence(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} must be between 0 and 1, such as 0.95")
    return value


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        "replicate",
        help="run many seeds per strategy and scenario into one results CSV",
        description=(
            "Run every chosen strategy against every chosen scenario on the same seeds, "
            "score each run, write one row per run to a results CSV, and print each "
            "metric's mean with a bootstrap confidence interval."
        ),
    )
    parser.add_argument(
        "--strategies",
        type=_names(list(STRATEGIES), "strategy"),
        default=list(STRATEGIES),
        metavar="LIST",
        help=f"comma-separated strategies (default all: {','.join(STRATEGIES)})",
    )
    parser.add_argument(
        "--scenarios",
        type=_names(list(SCENARIOS), "scenario"),
        default=list(SCENARIOS),
        metavar="LIST",
        help=f"comma-separated scenarios (default all: {','.join(SCENARIOS)})",
    )
    parser.add_argument(
        "--seeds",
        type=_positive_int,
        default=DEFAULT_SEEDS,
        metavar="N",
        help=f"how many seeds per strategy and scenario (default {DEFAULT_SEEDS})",
    )
    parser.add_argument(
        "--first-seed",
        type=_non_negative_int,
        default=DEFAULT_FIRST_SEED,
        metavar="SEED",
        help=f"seeds run from this one upward (default {DEFAULT_FIRST_SEED})",
    )
    parser.add_argument(
        "--duration",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help=f"simulated seconds per run (default {SimConfig().sim_s:g})",
    )
    parser.add_argument(
        "--onset",
        type=_non_negative_float,
        default=None,
        metavar="SECONDS",
        help="when the scenarios' attackers turn (default 0)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"where to write the results CSV (default {DEFAULT_OUTPUT}); overwritten",
    )
    parser.add_argument(
        "--summary",
        default=None,
        metavar="PATH",
        help="also write every mean and interval to this CSV",
    )
    parser.add_argument(
        "--confidence",
        type=_confidence,
        default=DEFAULT_CONFIDENCE,
        metavar="LEVEL",
        help=f"confidence level of the intervals (default {DEFAULT_CONFIDENCE:g})",
    )
    parser.add_argument(
        "--resamples",
        type=_positive_int,
        default=DEFAULT_RESAMPLES,
        metavar="N",
        help=f"bootstrap resamples per interval (default {DEFAULT_RESAMPLES:,})",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="print nothing unless something goes wrong"
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    if args.duration is not None:
        changes["sim_s"] = args.duration
    if args.onset is not None:
        changes["attack_start_s"] = args.onset
    config = replace(SimConfig(), **changes) if changes else None
    seeds = list(range(args.first_seed, args.first_seed + args.seeds))

    started = time.perf_counter()
    rows = replicate_rows(
        strategies=args.strategies, scenarios=args.scenarios, seeds=seeds, config=config
    )
    elapsed = time.perf_counter() - started

    try:
        write_results_csv(rows, args.output)
    except OSError as exc:
        print(f"turncoat replicate: cannot write {args.output}: {exc.strerror or exc}")
        return EXIT_UNREADABLE

    groups = bootstrap_metrics(
        rows, list(RESULT_METRICS), confidence=args.confidence, resamples=args.resamples
    )
    if args.summary is not None:
        try:
            write_summary(groups, args.summary)
        except OSError as exc:
            print(f"turncoat replicate: cannot write {args.summary}: {exc.strerror or exc}")
            return EXIT_UNREADABLE

    if not args.quiet:
        print(
            f"Ran {len(rows):,} runs ({_count(len(args.strategies), 'strategy', 'strategies')}"
            f" x {_count(len(args.scenarios), 'scenario')} x {_count(len(seeds), 'seed')}, "
            f"{seeds[0]} to {seeds[-1]}) in {elapsed:.0f} s"
        )
        print(f"Wrote {args.output} ({len(rows):,} rows, results format {RESULTS_VERSION})")
        if args.summary is not None:
            print(f"Wrote {args.summary}")
        print(
            f"\nMean over seeds, with {args.confidence:.0%} bootstrap confidence interval "
            f"[low, high] ({args.resamples:,} resamples)\n"
        )
        print(format_summary(groups, args.strategies, args.scenarios))
    return EXIT_OK
