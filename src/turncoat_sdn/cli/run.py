"""``turncoat run``: simulate one seeded run and record it to ``events.jsonl``.

Every run gets the same controller view, whatever the strategy: the real trust
calculator (:class:`SimTrustModel`) and the Sybil latency tell. Strategies
differ only in what they do with it, which is what makes runs comparable.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from pathlib import Path

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.routers import DESCRIPTIONS, STRATEGIES
from turncoat_sdn.events import EventWriter
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.sim import SCENARIOS, RunResult, SimConfig, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

DEFAULT_OUTPUT = "run.jsonl"
DEFAULT_SEED = 1
DEFAULT_STRATEGY = "zt_sdn"
DEFAULT_SCENARIO = "both"


def record_run(
    path: str | os.PathLike[str],
    *,
    strategy: str,
    scenario: str,
    seed: int,
    config: SimConfig | None = None,
) -> RunResult:
    """Simulate one run and record it to ``path``. Returns the run's metrics.

    Recording draws no random numbers, so the metrics equal those of an
    unrecorded :func:`turncoat_sdn.sim.simulate` call with the same arguments.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; expected one of {sorted(STRATEGIES)}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {list(SCENARIOS)}")
    with EventWriter(
        path, backend="sim", seed=seed, strategy=strategy, scenario=scenario
    ) as recorder:
        return simulate(
            STRATEGIES[strategy],
            scenario,
            seed,
            config=config,
            trust=SimTrustModel,
            latency_tell=latency_tell,
            name=strategy,
            recorder=recorder,
        )


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError(f"{text!r} must be a positive number of seconds")
    return value


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} must be 0 or more")
    return value


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    strategies = ", ".join(f"{name} ({DESCRIPTIONS[name]})" for name in STRATEGIES)
    parser = commands.add_parser(
        "run",
        help="simulate one seeded run and record it to events.jsonl",
        description=(
            "Simulate one seeded run of a load-balancing strategy against a scenario's "
            "attackers, and record every routing decision, outcome and quarantine to a "
            "JSONL file. The same seed gives every strategy the same workload."
        ),
        epilog=f"Strategies: {strategies}.",
    )
    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES),
        default=DEFAULT_STRATEGY,
        help=f"load-balancing strategy (default {DEFAULT_STRATEGY})",
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS),
        default=DEFAULT_SCENARIO,
        help=(
            "which servers attack: none, a Sybil, a dropper, both, a grayhole or an "
            "on-off Sybil "
            f"(default {DEFAULT_SCENARIO})"
        ),
    )
    parser.add_argument(
        "--seed",
        type=_non_negative_int,
        default=DEFAULT_SEED,
        help=f"fixes the workload and every random choice (default {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--duration",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help=f"simulated seconds (default {SimConfig().sim_s:g})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"where to write the recording (default {DEFAULT_OUTPUT}); overwritten if it exists",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="print nothing unless something goes wrong"
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    config = None
    if args.duration is not None:
        config = replace(SimConfig(), sim_s=args.duration)

    try:
        result = record_run(
            args.output,
            strategy=args.strategy,
            scenario=args.scenario,
            seed=args.seed,
            config=config,
        )
    except OSError as exc:
        print(f"turncoat run: cannot write {args.output}: {exc.strerror or exc}")
        return EXIT_UNREADABLE

    # A recording the scorers cannot read is a bug here, not the user's
    # problem, so check every file before reporting success.
    report = validate_file(args.output)
    if not report.ok:
        print(report.format(args.output))
        print("turncoat run: the recording failed validation; please report this as a bug.")
        return EXIT_FAILED

    if not args.quiet:
        print(_summary(Path(args.output), result, report.lines))
    return EXIT_OK


def _summary(path: Path, result: RunResult, lines: int) -> str:
    if result.time_to_isolate_s is None:
        isolated = "no server was isolated"
    else:
        isolated = f"first isolation at {result.time_to_isolate_s:g} s"
    return "\n".join(
        [
            f"Recorded {path} ({lines:,} lines, valid)",
            f"  {result.strategy} on {result.scenario}, seed {result.seed}: "
            f"{result.offered:,} tasks, {result.slo_violation_rate:.1%} SLO violations, "
            f"{isolated}",
            f"Next: turncoat score {path}",
        ]
    )
