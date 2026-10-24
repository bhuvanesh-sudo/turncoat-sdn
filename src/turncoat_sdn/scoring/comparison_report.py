"""Descriptive comparisons of strategy benchmark summaries for v0.3."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from turncoat_sdn.scoring.benchmark import BenchmarkSummary

METRICS = (
    ("detection_rate", "Detection rate", "max"),
    ("false_positive_rate", "False-positive rate", "min"),
    ("mean_detection_latency_s", "Mean detection latency (s)", "min"),
)


def load_summaries(path: str | Path) -> list[BenchmarkSummary]:
    """Load benchmark summaries previously exported as JSON."""
    source = Path(path)
    try:
        data: Any = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid benchmark JSON: {source}") from exc

    if not isinstance(data, list):
        raise ValueError("Benchmark JSON must contain a list of summaries")

    summaries = []
    required = set(BenchmarkSummary.__dataclass_fields__)
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Summary at index {index} must be an object")
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Summary at index {index} is missing fields: {sorted(missing)}")
        try:
            summaries.append(BenchmarkSummary(**item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid summary at index {index}: {exc}") from exc
    return summaries


def compare_summaries(
    summaries: list[BenchmarkSummary],
) -> list[dict[str, Any]]:
    """Compare metric values and report observed leaders, including ties.

    This is descriptive only. It does not perform hypothesis tests or infer
    that observed differences are statistically significant.
    """
    report: list[dict[str, Any]] = []

    for metric, label, direction in METRICS:
        available = [
            (summary.name, getattr(summary, metric))
            for summary in summaries
            if getattr(summary, metric) is not None
        ]
        if not available:
            best_value = None
            leaders: list[str] = []
        else:
            best_value = (
                max(value for _, value in available)
                if direction == "max"
                else min(value for _, value in available)
            )
            leaders = [name for name, value in available if value == best_value]

        report.append(
            {
                "metric": metric,
                "label": label,
                "preferred_direction": direction,
                "best_value": best_value,
                "leaders": leaders,
                "values": [{"strategy": name, "value": value} for name, value in available],
                "strategies_without_value": [
                    summary.name for summary in summaries if getattr(summary, metric) is None
                ],
            }
        )

    return report


def write_comparison_report(
    report: list[dict[str, Any]],
    json_path: str | Path,
    csv_path: str | Path,
) -> None:
    """Write a detailed JSON report and a flat CSV metric table."""
    json_destination = Path(json_path)
    csv_destination = Path(csv_path)
    json_destination.parent.mkdir(parents=True, exist_ok=True)
    csv_destination.parent.mkdir(parents=True, exist_ok=True)

    json_destination.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    with csv_destination.open("w", newline="", encoding="utf-8") as handle:
        fields = (
            "metric",
            "label",
            "preferred_direction",
            "strategy",
            "value",
            "is_observed_leader",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for metric_report in report:
            for entry in metric_report["values"]:
                writer.writerow(
                    {
                        "metric": metric_report["metric"],
                        "label": metric_report["label"],
                        "preferred_direction": metric_report["preferred_direction"],
                        "strategy": entry["strategy"],
                        "value": entry["value"],
                        "is_observed_leader": (entry["strategy"] in metric_report["leaders"]),
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare existing v0.3 strategy benchmark summaries."
    )
    parser.add_argument(
        "input",
        help="JSON produced by the strategy benchmark runner",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark-results",
        help="directory for comparison-report JSON and CSV",
    )
    args = parser.parse_args()

    summaries = load_summaries(args.input)
    report = compare_summaries(summaries)

    output_dir = Path(args.output_dir)
    json_path = output_dir / "strategy-comparison.json"
    csv_path = output_dir / "strategy-comparison.csv"
    write_comparison_report(report, json_path, csv_path)

    for metric_report in report:
        best = metric_report["best_value"]
        if best is None:
            print(f"{metric_report['label']}: no values available")
        else:
            print(
                f"{metric_report['label']}: {best} "
                f"(observed leader(s): {', '.join(metric_report['leaders'])})"
            )
    print(f"Comparison reports written to: {output_dir}")


if __name__ == "__main__":
    main()
