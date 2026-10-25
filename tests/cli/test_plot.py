"""Tests for ``turncoat plot``, the comparison figure."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.plot import axis_ticks, render_figure
from turncoat_sdn.cli.replicate import format_interval, replicate_rows
from turncoat_sdn.stats import bootstrap_metrics, read_results, write_results

SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def rows():
    """A small paired grid: two strategies, an attacked and a clean scenario."""
    return replicate_rows(
        strategies=["zt_sdn", "round_robin"], scenarios=["both", "clean"], seeds=[1, 2, 3]
    )


@pytest.fixture
def results_file(rows, tmp_path):
    path = tmp_path / "results.csv"
    write_results(rows, path)
    return path


def _marks(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return [g.find(f"{SVG}title").text for g in root.iter(f"{SVG}g") if g.get("class") == "mark"]


class TestAxisTicks:
    @pytest.mark.parametrize(
        ("high", "expected"),
        [
            (12.34, [0, 5, 10, 15]),
            (38.19, [0, 10, 20, 30, 40]),
            (1696.8, [0, 500, 1000, 1500, 2000]),
            (0.257, [0, 0.1, 0.2, 0.3]),
            (100.0, [0, 25, 50, 75, 100]),
            (0.0, [0, 1]),
        ],
    )
    def test_round_ticks_from_zero_covering_the_data(self, high, expected):
        assert axis_ticks(high) == pytest.approx(expected)


class TestRenderFigure:
    def test_is_well_formed_svg_with_a_panel_per_scenario(self, rows):
        svg = render_figure(rows)
        root = ET.fromstring(svg)
        assert root.tag == f"{SVG}svg"
        titles = [t.text for t in root.iter(f"{SVG}text") if t.get("class") == "panel-title"]
        assert titles == ["both", "clean"]

    def test_marks_carry_the_same_intervals_replicate_prints(self, rows):
        svg = render_figure(rows, "slo_violation_rate")
        groups = bootstrap_metrics(rows, ["slo_violation_rate"])
        expected = [
            f"{g['strategy']}, {g['scenario']}: "
            f"{format_interval(g['slo_violation_rate'], '%')} (3 runs)"
            for g in groups
        ]
        assert sorted(_marks(svg)) == sorted(expected)

    def test_unmeasured_cells_are_marked_not_drawn(self, rows):
        # Nothing is isolated in clean, so its two cells have no mark.
        svg = render_figure(rows, "time_to_isolate_s")
        marks = _marks(svg)
        assert len(marks) == 2
        assert all(", both:" in m for m in marks)
        assert svg.count(">n/a</text>") == 2

    def test_only_the_highlighted_strategy_is_coloured(self, rows):
        svg = render_figure(rows, highlight="zt_sdn")
        assert svg.count('class="dot highlight"') == 2
        assert svg.count('class="dot"') == 2
        assert 'class="label highlight"' in svg
        none = render_figure(rows, highlight=None)
        assert 'class="dot highlight"' not in none

    def test_every_panel_shares_one_axis(self, rows):
        svg = render_figure(rows, "slo_violation_rate")
        ticks = re.findall(r'class="tick"[^>]*>([^<]+)<', svg)
        per_panel = len(ticks) // 2
        assert ticks[:per_panel] == ticks[per_panel:]

    def test_follows_the_dark_theme(self, rows):
        assert "prefers-color-scheme: dark" in render_figure(rows)

    def test_is_deterministic(self, rows):
        assert render_figure(rows) == render_figure(rows)

    def test_order_follows_the_arguments(self, rows):
        svg = render_figure(rows, strategies=["round_robin", "zt_sdn"], scenarios=["clean"])
        labels = re.findall(r'class="label[^"]*"[^>]*>([^<]+)<', svg)
        assert labels == ["round_robin", "zt_sdn"]

    def test_unknown_metric_is_refused(self, rows):
        with pytest.raises(ValueError, match="unknown metric"):
            render_figure(rows, "offered")

    def test_missing_strategy_is_refused(self, rows):
        with pytest.raises(ValueError, match="no rows found for 'least_conn'"):
            render_figure(rows, strategies=["zt_sdn", "least_conn"])


class TestPlotCommand:
    def test_writes_the_figure(self, turncoat, results_file, tmp_path):
        output = tmp_path / "figures" / "slo.svg"
        code, printed = turncoat("plot", str(results_file), "-o", str(output))
        assert code == EXIT_OK
        assert printed == f"Wrote {output} (SLO violations (%))\n"
        assert output.read_text(encoding="utf-8") == render_figure(read_results(results_file))

    def test_options_reach_the_figure(self, turncoat, results_file, tmp_path):
        output = tmp_path / "fig.svg"
        code, _ = turncoat(
            "plot",
            str(results_file),
            "--metric",
            "malicious_share",
            "--scenarios",
            "both",
            "--highlight",
            "none",
            "--confidence",
            "0.9",
            "-o",
            str(output),
            "-q",
        )
        assert code == EXIT_OK
        svg = output.read_text(encoding="utf-8")
        assert "Routed to attackers (%): mean over 3 seeds, with 90% confidence" in svg
        assert ">clean</text>" not in svg
        assert "highlight" not in svg.split("</style>", 1)[1]

    def test_quiet(self, turncoat, results_file, tmp_path):
        code, printed = turncoat("plot", str(results_file), "-o", str(tmp_path / "q.svg"), "-q")
        assert (code, printed) == (EXIT_OK, "")

    def test_missing_file_is_unreadable(self, turncoat, tmp_path):
        code, printed = turncoat("plot", str(tmp_path / "missing.csv"))
        assert code == EXIT_UNREADABLE
        assert "cannot read" in printed

    def test_invalid_file_fails(self, turncoat, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("not,a,results,file\n", encoding="utf-8")
        code, printed = turncoat("plot", str(path), "-o", str(tmp_path / "x.svg"))
        assert code == EXIT_FAILED
        assert "turncoat plot:" in printed

    def test_strategy_not_in_file_fails(self, turncoat, results_file, tmp_path):
        code, printed = turncoat(
            "plot", str(results_file), "--strategies", "least_conn", "-o", str(tmp_path / "x.svg")
        )
        assert code == EXIT_FAILED
        assert "no rows found for 'least_conn'" in printed

    def test_unknown_metric_is_a_usage_error(self, turncoat, results_file):
        code, _ = turncoat("plot", str(results_file), "--metric", "offered")
        assert code == EXIT_UNREADABLE
