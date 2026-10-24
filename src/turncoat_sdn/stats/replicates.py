"""The replicate results file: one tidy CSV row per run, every metric a column.

A comparison needs many runs of every strategy on every scenario, on shared
seeds. ``turncoat replicate`` runs them and writes them here, one row per run,
so the statistics, a spreadsheet or a plotting script all read the same file.
This module owns that file's format: its columns in order, the detection
columns worked out from a scored run, and a writer and reader that agree.

The format is versioned by :data:`RESULTS_VERSION` and described in
``docs/event-format.md``. Columns are only ever added at the end; a reader
should look columns up by name.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: Version of the results format. Bumped when a reader would notice.
RESULTS_VERSION = "1.0"

#: Identify the run.
KEY_FIELDS: tuple[str, ...] = ("strategy", "scenario", "seed")

#: Every column, in order. The first thirteen are the simulator's own per-run
#: row (``turncoat_sdn.sim.CSV_FIELDS``); the rest come from scoring the run's
#: recording. A test keeps the two lists in step.
RESULTS_FIELDS: tuple[str, ...] = (
    *KEY_FIELDS,
    "offered",
    "completed",
    "failed",
    "slo_violation_rate",
    "failure_rate",
    "malicious_share",
    "mean_latency_ms",
    "p95_latency_ms",
    "gini",
    "time_to_isolate_s",
    "attackers",
    "attackers_named",
    "detection_rate",
    "mean_detection_latency_s",
    "honest_subjects",
    "honest_mislabelled",
    "false_positive_rate",
)

#: The columns statistics are taken over. ``True`` means lower is better.
RESULT_METRICS: dict[str, bool] = {
    "slo_violation_rate": True,
    "failure_rate": True,
    "malicious_share": True,
    "mean_latency_ms": True,
    "p95_latency_ms": True,
    "gini": True,
    "time_to_isolate_s": True,
    "detection_rate": False,
    "mean_detection_latency_s": True,
    "false_positive_rate": True,
}

_TEXT = {"strategy", "scenario"}
_COUNTS = {
    "seed",
    "offered",
    "completed",
    "failed",
    "attackers",
    "attackers_named",
    "honest_subjects",
    "honest_mislabelled",
}
_DECIMALS = 6


def detection_columns(results: Iterable[Any]) -> dict[str, Any]:
    """The detection columns for one run, from its scored subjects.

    ``results`` are the :class:`turncoat_sdn.scoring.attack_report.SubjectResult`
    objects ``score_run`` returns for the run. An attacker counts as named
    when the scorer's verdict is its exact label. Latency is averaged over
    named attackers whose onset is known. A rate with nothing to measure, such
    as the detection rate of a run with no attacker, is ``None`` (a blank
    cell), never 0.
    """
    attackers = named = honest = mislabelled = 0
    latencies: list[float] = []
    for result in results:
        if result.truth == "none":
            honest += 1
            if result.predicted != "none":
                mislabelled += 1
            continue
        attackers += 1
        if result.correct:
            named += 1
            latency = result.detection_latency_s
            if latency is not None and latency >= 0:
                latencies.append(float(latency))

    def rate(part: float, whole: float) -> float | None:
        return round(part / whole, _DECIMALS) if whole else None

    return {
        "attackers": attackers,
        "attackers_named": named,
        "detection_rate": rate(named, attackers),
        "mean_detection_latency_s": rate(sum(latencies), len(latencies)),
        "honest_subjects": honest,
        "honest_mislabelled": mislabelled,
        "false_positive_rate": rate(mislabelled, honest),
    }


def results_row(run_row: Mapping[str, Any], scored: Iterable[Any]) -> dict[str, Any]:
    """Join the simulator's row for a run with its detection columns, in order."""
    row = {**run_row, **detection_columns(scored)}
    missing = [name for name in RESULTS_FIELDS if name not in row]
    if missing:
        raise ValueError(f"run row is missing columns: {', '.join(missing)}")
    return {name: row[name] for name in RESULTS_FIELDS}


def write_results(rows: Iterable[Mapping[str, Any]], path: str | os.PathLike[str]) -> int:
    """Write rows to ``path`` as the results CSV. Returns how many rows were written.

    ``None`` is written as a blank cell. Parent folders are created.
    """
    folder = os.path.dirname(os.fspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(RESULTS_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in RESULTS_FIELDS})
            count += 1
    return count


def _parse(name: str, text: str, line: int) -> Any:
    if name in _TEXT:
        return text
    if text == "":
        if name in _COUNTS:
            raise ValueError(f"line {line}: column {name!r} must not be blank")
        return None
    try:
        return int(text) if name in _COUNTS else float(text)
    except ValueError:
        raise ValueError(f"line {line}: column {name!r} is not a number: {text!r}") from None


def read_results(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read a results CSV back into typed rows.

    Counts come back as ``int``, rates and times as ``float``, and blank cells
    as ``None``. Columns after the known ones, from a newer minor version, are
    kept as text.

    Raises:
        ValueError: The header does not start with :data:`RESULTS_FIELDS`, or a
            cell does not parse.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None or tuple(header[: len(RESULTS_FIELDS)]) != RESULTS_FIELDS:
            raise ValueError(
                f"{os.fspath(path)} is not a turncoat results file: its header must start "
                f"with {', '.join(RESULTS_FIELDS[:4])}, ..."
            )
        rows: list[dict[str, Any]] = []
        for line, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if len(cells) != len(header):
                raise ValueError(f"line {line}: expected {len(header)} cells, got {len(cells)}")
            row = {
                name: _parse(name, text, line) if name in RESULTS_FIELDS else text
                for name, text in zip(header, cells, strict=True)
            }
            rows.append(row)
    return rows


def runs_per_group(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[int]]:
    """The seeds each (strategy, scenario) ran on, in file order."""
    groups: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        groups.setdefault((row["strategy"], row["scenario"]), []).append(row["seed"])
    return groups
