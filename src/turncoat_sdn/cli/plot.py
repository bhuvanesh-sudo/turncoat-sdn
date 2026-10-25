"""``turncoat plot``: the comparison figure, drawn from a results CSV.

Reads the results file ``turncoat replicate`` writes and draws one metric as
small multiples: a panel per scenario, a row per strategy, a dot at the mean
over seeds and a line across its percentile-bootstrap confidence interval.
The intervals are the ones ``replicate`` prints, from
:func:`~turncoat_sdn.stats.bootstrap_metrics` with the same seed, so the
figure and the table always agree.

Every panel shares one x-axis, so a gap reads the same in every scenario. One
strategy, ``zt_sdn`` by default, is drawn in colour and the rest in grey;
each row is labelled by name, so no reader has to match colours. The figure
is a self-contained SVG with no plotting library behind it: it follows the
viewer's light or dark theme, every mark carries a tooltip with its numbers,
and the same file and options give the same bytes every time.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import math
import os
from collections.abc import Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape

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
from turncoat_sdn.stats import RESULT_METRICS, ConfidenceInterval, bootstrap_metrics, read_results
from turncoat_sdn.stats.bootstrap import DEFAULT_CONFIDENCE, DEFAULT_RESAMPLES, DEFAULT_SEED

DEFAULT_OUTPUT = "comparison.svg"
DEFAULT_METRIC = "slo_violation_rate"
DEFAULT_HIGHLIGHT = "zt_sdn"
DEFAULT_COLUMNS = 4

# Layout, in SVG pixels.
_MARGIN = 24
_LABEL_GAP = 12
_PANEL_WIDTH = 176
_PANEL_GAP = 28
_ROW_HEIGHT = 22
_PANEL_TITLE = 26
_AXIS_HEIGHT = 30
_GRID_GAP = 18
_HEADER = 64
_FOOTER = 52
_CHAR_WIDTH = 7.2  # a generous average at 12 px, for sizing the label column

_STYLE = """
  .surface { fill: #fcfcfb; }
  .title { fill: #0b0b0b; font-size: 16px; font-weight: 600; }
  .subtitle, .note { fill: #52514e; font-size: 12px; }
  .panel-title { fill: #0b0b0b; font-size: 13px; font-weight: 600; }
  .label { fill: #52514e; font-size: 12px; }
  .label.highlight { fill: #0b0b0b; font-weight: 600; }
  .tick { fill: #6f6e69; font-size: 11px; font-variant-numeric: tabular-nums; }
  .na { fill: #6f6e69; font-size: 11px; font-style: italic; }
  .grid { stroke: #e4e3df; stroke-width: 1; }
  .baseline { stroke: #b9b8b2; stroke-width: 1; }
  .ci { stroke: #9a9893; stroke-width: 2; stroke-linecap: round; }
  .dot { fill: #9a9893; stroke: #fcfcfb; stroke-width: 2; }
  .ci.highlight { stroke: #2a78d6; }
  .dot.highlight { fill: #2a78d6; }
  .hit { fill: transparent; }
  .mark:hover .ci { stroke-width: 3; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; }
    .title, .panel-title, .label.highlight { fill: #f0efec; }
    .subtitle, .note, .label { fill: #c3c2b7; }
    .tick, .na { fill: #9d9c94; }
    .grid { stroke: #2e2e2c; }
    .baseline { stroke: #55544f; }
    .ci { stroke: #77766f; }
    .dot { fill: #77766f; stroke: #1a1a19; }
    .ci.highlight { stroke: #3987e5; }
    .dot.highlight { fill: #3987e5; }
  }
"""


def _nice_step(span: float, ticks: int = 4) -> float:
    """A round tick step (1, 2, 2.5 or 5 times a power of ten) giving about ``ticks`` ticks."""
    raw = span / ticks
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if factor * power >= raw:
            return factor * power
    return 10 * power  # pragma: no cover - the loop always returns


def axis_ticks(high: float) -> list[float]:
    """Ticks from 0 up to the first round value at or above ``high``."""
    if high <= 0:
        return [0.0, 1.0]
    step = _nice_step(high)
    count = math.ceil(high / step - 1e-9)
    return [round(i * step, 10) for i in range(count + 1)]


def _scale(style: str) -> float:
    return 100.0 if style == "%" else 1.0


def _tick_text(value: float, step: float) -> str:
    decimals = 0
    while decimals < 6 and abs(round(step, decimals) - step) > 1e-9:
        decimals += 1
    return f"{value:,.{decimals}f}"


def _fmt(value: float) -> str:
    """A coordinate with at most one decimal, so the output is stable."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def render_figure(
    rows: Sequence[Mapping[str, Any]],
    metric: str = DEFAULT_METRIC,
    *,
    strategies: Sequence[str] | None = None,
    scenarios: Sequence[str] | None = None,
    highlight: str | None = DEFAULT_HIGHLIGHT,
    columns: int = DEFAULT_COLUMNS,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> str:
    """The comparison figure for ``metric`` as an SVG document.

    ``strategies`` and ``scenarios`` default to those in ``rows``, in the order
    they first appear. ``highlight`` names the strategy drawn in colour, or
    ``None`` for all grey.

    Raises:
        ValueError: ``metric`` is not a results metric, ``columns`` is below 1,
            or a strategy has no runs in a scenario.
    """
    if metric not in RESULT_METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {list(RESULT_METRICS)}")
    if columns < 1:
        raise ValueError("columns must be 1 or more")
    strategies = list(strategies or dict.fromkeys(row["strategy"] for row in rows))
    scenarios = list(scenarios or dict.fromkeys(row["scenario"] for row in rows))
    available = {(row.get("strategy"), row.get("scenario")) for row in rows}
    for scenario in scenarios:
        for strategy in strategies:
            if (strategy, scenario) not in available:
                raise ValueError(f"no rows found for {strategy!r} in scenario {scenario!r}")

    chosen = [r for r in rows if r.get("strategy") in strategies and r.get("scenario") in scenarios]
    groups = bootstrap_metrics(
        chosen, [metric], confidence=confidence, resamples=resamples, seed=seed
    )
    cells: dict[tuple[str, str], ConfidenceInterval] = {
        (g["strategy"], g["scenario"]): g[metric] for g in groups
    }
    runs = max(g["runs"] for g in groups)

    label, style = METRIC_LABELS.get(metric, (metric, ".4g"))
    scale = _scale(style)
    highs = [ci.high * scale for ci in cells.values() if ci.high is not None]
    ticks = axis_ticks(max(highs, default=0.0))
    top = ticks[-1]
    step = ticks[1] - ticks[0]

    label_width = math.ceil(max(len(s) for s in strategies) * _CHAR_WIDTH)
    columns = min(columns, len(scenarios))
    grid_rows = math.ceil(len(scenarios) / columns)
    panel_height = _PANEL_TITLE + len(strategies) * _ROW_HEIGHT + _AXIS_HEIGHT
    plot_left = _MARGIN + label_width + _LABEL_GAP
    width = plot_left + columns * _PANEL_WIDTH + (columns - 1) * _PANEL_GAP + _MARGIN
    height = _HEADER + grid_rows * panel_height + (grid_rows - 1) * _GRID_GAP + _FOOTER

    level = f"{confidence * 100:g}%"
    title = f"{label}: mean over {runs} seeds, with {level} confidence interval"
    unit = "lower is better" if RESULT_METRICS[metric] else "higher is better"
    subtitle = f"One panel per scenario, one row per strategy; {unit}."

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="figure-title figure-desc" '
        "font-family=\"system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif\">",
        f'<title id="figure-title">{escape(title)}</title>',
        f'<desc id="figure-desc">{escape(subtitle)} Generated by turncoat plot.</desc>',
        f"<style>{_STYLE}</style>",
        f'<rect class="surface" width="{width}" height="{height}"/>',
        f'<text class="title" x="{_MARGIN}" y="{_MARGIN + 6}">{escape(title)}</text>',
        f'<text class="subtitle" x="{_MARGIN}" y="{_MARGIN + 26}">{escape(subtitle)}</text>',
    ]

    def x_of(value: float) -> float:
        return min(value / top, 1.0) * _PANEL_WIDTH if top else 0.0

    for index, scenario in enumerate(scenarios):
        column, grid_row = index % columns, index // columns
        left = plot_left + column * (_PANEL_WIDTH + _PANEL_GAP)
        panel_top = _HEADER + grid_row * (panel_height + _GRID_GAP)
        rows_top = panel_top + _PANEL_TITLE
        rows_bottom = rows_top + len(strategies) * _ROW_HEIGHT
        out.append(f'<g class="panel" transform="translate({_fmt(left)},0)">')
        out.append(
            f'<text class="panel-title" x="0" y="{_fmt(panel_top + 14)}">{escape(scenario)}</text>'
        )
        for tick in ticks:
            x = _fmt(x_of(tick))
            out.append(
                f'<line class="{"baseline" if tick == 0 else "grid"}" x1="{x}" x2="{x}" '
                f'y1="{_fmt(rows_top)}" y2="{_fmt(rows_bottom)}"/>'
            )
            anchor = "start" if tick == 0 else "end" if tick == top else "middle"
            out.append(
                f'<text class="tick" x="{x}" y="{_fmt(rows_bottom + 16)}" '
                f'text-anchor="{anchor}">{_tick_text(tick, step)}</text>'
            )
        for position, strategy in enumerate(strategies):
            y = rows_top + (position + 0.5) * _ROW_HEIGHT
            accent = " highlight" if strategy == highlight else ""
            if column == 0:
                out.append(
                    f'<text class="label{accent}" x="{_fmt(-_LABEL_GAP)}" y="{_fmt(y + 4)}" '
                    f'text-anchor="end">{escape(strategy)}</text>'
                )
            interval = cells[(strategy, scenario)]
            if interval.mean is None or interval.low is None or interval.high is None:
                out.append(f'<text class="na" x="4" y="{_fmt(y + 4)}">n/a</text>')
                continue
            low, mean, high = (
                x_of(v * scale) for v in (interval.low, interval.mean, interval.high)
            )
            tip = f"{strategy}, {scenario}: {format_interval(interval, style)} ({interval.n} runs)"
            out.append(f'<g class="mark"><title>{escape(tip)}</title>')
            out.append(
                f'<rect class="hit" x="0" y="{_fmt(y - _ROW_HEIGHT / 2)}" '
                f'width="{_PANEL_WIDTH}" height="{_ROW_HEIGHT}"/>'
            )
            out.append(
                f'<line class="ci{accent}" x1="{_fmt(low)}" x2="{_fmt(high)}" '
                f'y1="{_fmt(y)}" y2="{_fmt(y)}"/>'
            )
            out.append(f'<circle class="dot{accent}" cx="{_fmt(mean)}" cy="{_fmt(y)}" r="4.5"/>')
            out.append("</g>")
        out.append("</g>")

    notes = (
        f"Dot: mean over seeds. Line: {level} percentile bootstrap interval "
        f"({resamples:,} resamples, seed {seed}); one narrower than the dot is hidden by it.",
        "Every panel shares one axis. n/a: no run measured it. Generated by turncoat plot.",
    )
    for line, note in enumerate(notes):
        note_y = height - _FOOTER + 22 + line * 16
        out.append(f'<text class="note" x="{_MARGIN}" y="{note_y}">{escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the plot subcommand."""
    parser = commands.add_parser(
        "plot",
        help="draw the comparison figure from a results CSV",
        description=(
            "Draw one metric from a replicate results file as an SVG figure: a panel per "
            "scenario, a row per strategy, the mean over seeds with its bootstrap "
            "confidence interval, on one shared axis."
        ),
        epilog="Exit status: 0 when drawn, 1 when the results file is invalid or cannot be "
        "drawn, 2 when a file cannot be read or written or an option is wrong.",
    )
    parser.add_argument("results", metavar="RESULTS.csv", help="replicate results CSV")
    parser.add_argument(
        "--metric",
        choices=list(RESULT_METRICS),
        default=DEFAULT_METRIC,
        metavar="NAME",
        help=f"the metric to draw (default: {DEFAULT_METRIC})",
    )
    parser.add_argument(
        "--strategies",
        type=_names(list(STRATEGIES), "strategy"),
        default=None,
        metavar="LIST",
        help="comma-separated strategies, one row each (default: every one in the file)",
    )
    parser.add_argument(
        "--scenarios",
        type=_names(list(SCENARIOS), "scenario"),
        default=None,
        metavar="LIST",
        help="comma-separated scenarios, one panel each (default: every one in the file)",
    )
    parser.add_argument(
        "--highlight",
        default=DEFAULT_HIGHLIGHT,
        metavar="STRATEGY",
        help=f"the strategy drawn in colour, or 'none' (default: {DEFAULT_HIGHLIGHT})",
    )
    parser.add_argument(
        "--columns",
        type=_positive_int,
        default=DEFAULT_COLUMNS,
        metavar="N",
        help=f"panels per row (default: {DEFAULT_COLUMNS})",
    )
    parser.add_argument(
        "--confidence",
        type=_confidence,
        default=DEFAULT_CONFIDENCE,
        metavar="LEVEL",
        help=f"coverage of the intervals (default: {DEFAULT_CONFIDENCE:g})",
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
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"where to write the SVG (default: {DEFAULT_OUTPUT}); overwritten",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="print nothing unless something goes wrong"
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    """Read results, draw the figure and write it."""
    try:
        rows = read_results(args.results)
    except OSError as exc:
        print(f"turncoat plot: cannot read {args.results}: {exc.strerror or exc}")
        return EXIT_UNREADABLE
    except (UnicodeError, ValueError) as exc:
        print(f"turncoat plot: invalid results file {args.results}: {exc}")
        return EXIT_FAILED
    if not rows:
        print(f"turncoat plot: invalid results file {args.results}: it has no runs")
        return EXIT_FAILED

    highlight = None if args.highlight.lower() == "none" else args.highlight
    try:
        svg = render_figure(
            rows,
            args.metric,
            strategies=args.strategies,
            scenarios=args.scenarios,
            highlight=highlight,
            columns=args.columns,
            confidence=args.confidence,
            resamples=args.resamples,
        )
    except (TypeError, ValueError) as exc:
        print(f"turncoat plot: cannot draw results: {exc}")
        return EXIT_FAILED

    try:
        folder = os.path.dirname(os.fspath(args.output))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
    except OSError as exc:
        print(f"turncoat plot: cannot write {args.output}: {exc.strerror or exc}")
        return EXIT_UNREADABLE

    if not args.quiet:
        label = METRIC_LABELS.get(args.metric, (args.metric, ""))[0]
        print(f"Wrote {args.output} ({label})")
    return EXIT_OK


__all__ = ["axis_ticks", "render_figure"]
