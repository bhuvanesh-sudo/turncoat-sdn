"""Run reproducible v0.3 comparisons across existing routing strategies."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.scoring.benchmark import (
    BenchmarkSummary,
    summarize_results,
    write_csv,
    write_json,
)

STRATEGIES = (
    "random",
    "round_robin",
    "least_conn",
    "no_trust",
    "zt_sdn",
)
SCENARIOS = ("clean", "sybil", "drop", "both")


def read_recording(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL recording, rejecting malformed JSON and non-object events."""
    events: list[dict[str, Any]] = []

    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Expected a JSON object in {path} at line {line_number}")
            events.append(event)

    if not events:
        raise ValueError(f"Recording is empty: {path}")
    return events


def run_benchmark(
    *,
    strategies: Sequence[str] = STRATEGIES,
    scenarios: Sequence[str] = SCENARIOS,
    seeds: Sequence[int] = (1, 2, 3),
    duration: float = 120,
    output_dir: str | Path = "benchmark-results",
    executable: str = "turncoat",
) -> list[BenchmarkSummary]:
    """Run every requested strategy/scenario/seed combination.

    Each strategy receives the same scenario and seed combinations. The
    recording files are temporary; only aggregate JSON and CSV reports remain.
    """
    if not strategies:
        raise ValueError("At least one strategy is required")
    if not scenarios:
        raise ValueError("At least one scenario is required")
    if not seeds:
        raise ValueError("At least one seed is required")
    if duration <= 0:
        raise ValueError("Duration must be positive")

    invalid_strategies = set(strategies) - set(STRATEGIES)
    invalid_scenarios = set(scenarios) - set(SCENARIOS)
    if invalid_strategies:
        raise ValueError(f"Unknown strategies: {sorted(invalid_strategies)}")
    if invalid_scenarios:
        raise ValueError(f"Unknown scenarios: {sorted(invalid_scenarios)}")

    results_by_strategy: dict[str, list[list[Any]]] = {strategy: [] for strategy in strategies}

    with tempfile.TemporaryDirectory(prefix="turncoat-benchmark-") as temp_dir:
        temp_path = Path(temp_dir)

        for scenario in scenarios:
            for seed in seeds:
                for strategy in strategies:
                    recording = temp_path / (f"{strategy}-{scenario}-seed-{seed}.jsonl")
                    command = [
                        executable,
                        "run",
                        "--strategy",
                        strategy,
                        "--scenario",
                        scenario,
                        "--seed",
                        str(seed),
                        "--duration",
                        str(duration),
                        "--output",
                        str(recording),
                        "--quiet",
                    ]
                    subprocess.run(command, check=True)
                    events = read_recording(recording)
                    results_by_strategy[strategy].append(score_run(events))

    summaries = [
        summarize_results(strategy, results_by_strategy[strategy]) for strategy in strategies
    ]

    destination = Path(output_dir)
    write_json(summaries, destination / "strategy-benchmark.json")
    write_csv(summaries, destination / "strategy-benchmark.csv")
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare routing strategies using reproducible v0.3 runs."
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=STRATEGIES,
        default=list(STRATEGIES),
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=SCENARIOS,
        default=list(SCENARIOS),
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--output-dir", default="benchmark-results")
    parser.add_argument("--executable", default="turncoat")
    args = parser.parse_args()

    summaries = run_benchmark(
        strategies=args.strategies,
        scenarios=args.scenarios,
        seeds=args.seeds,
        duration=args.duration,
        output_dir=args.output_dir,
        executable=args.executable,
    )

    for summary in summaries:
        rate = "n/a" if summary.detection_rate is None else f"{summary.detection_rate:.1%}"
        print(
            f"{summary.name}: runs={summary.runs}, "
            f"detection_rate={rate}, "
            f"false_positives={summary.false_positives}"
        )
    print(f"Reports written to: {Path(args.output_dir)}")


if __name__ == "__main__":
    main()
