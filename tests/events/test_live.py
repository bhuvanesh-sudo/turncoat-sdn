"""Live recordings from the final-year controller convert to schema 1.0 and score unchanged."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from turncoat_sdn.cli import main
from turncoat_sdn.cli.score import score_recording, to_json
from turncoat_sdn.events import (
    ConversionError,
    convert_live_events,
    convert_live_file,
    read_events,
)
from turncoat_sdn.events.live import read_live_recording, write_recording
from turncoat_sdn.events.validate import validate_events, validate_file

HERE = Path(__file__).parent
FYP_LIVE = HERE / "fyp_live_run.jsonl"

#: A wall-clock start like the final-year controller's ``time.time()``.
WALL_T0 = 1761390000.25

GRAPH = {
    "nodes": [
        {"id": "srv1", "kind": "server", "attack": "none"},
        {"id": "srv2", "kind": "server", "attack": "sybil", "attack_start_s": 5.0},
        {"id": "iot1", "kind": "iot", "ip": "10.0.0.101", "attack": "none"},
    ],
    "links": [],
}


def livened(events: list[dict]) -> list[dict]:
    """A schema 1.0 recording put back in the final-year controller's shape.

    No header, wall-clock ``ts`` and a ``seq`` on every event, and one pair of
    neighbouring lines with different stamps swapped, as the bus's race could
    leave them.
    """
    body = [
        {**e, "ts": e["ts"] + WALL_T0, "seq": seq}
        for seq, e in enumerate((e for e in events if e["type"] != "header"), 1)
    ]
    i = next(i for i in range(2, len(body) - 1) if body[i]["ts"] < body[i + 1]["ts"])
    body[i], body[i + 1] = body[i + 1], body[i]
    return body


# --------------------------------------------------------------------------- #
# Converting a final-year recording
# --------------------------------------------------------------------------- #


def test_the_fixture_is_not_valid_as_written():
    report = validate_file(FYP_LIVE)
    assert not report.ok
    assert "the first line must be the header" in str(report.problems[0])


def test_converted_fixture_validates(tmp_path):
    out = tmp_path / "live.jsonl"
    conversion = convert_live_file(FYP_LIVE, out, strategy="zt_sdn")
    report = validate_file(out)
    assert report.ok, report.format(str(out))
    assert read_events(out) == conversion.events


def test_conversion_counts_what_it_changed():
    raw, skipped = read_live_recording(FYP_LIVE)
    conversion = convert_live_events(raw, skipped_lines=skipped)
    assert conversion.skipped_lines == 1  # the truncated tail line
    assert conversion.out_of_order == 1
    assert conversion.non_finite == 1
    assert conversion.untimed == 0
    assert conversion.started_at == WALL_T0
    notes = "\n".join(conversion.notes())
    assert "out of time order" in notes
    assert "written as null" in notes


def test_header_says_live_and_how_the_run_was_made():
    raw, _ = read_live_recording(FYP_LIVE)
    header = convert_live_events(raw, seed=3, strategy="zt_sdn", scenario="sybil").events[0]
    assert header == {
        "type": "header",
        "schema_version": "1.0",
        "backend": "live",
        "seed": 3,
        "strategy": "zt_sdn",
        "scenario": "sybil",
        "started_at": WALL_T0,
    }


def test_ts_counts_from_the_start_in_time_order_without_seq():
    raw, _ = read_live_recording(FYP_LIVE)
    events = convert_live_events(raw).events
    assert events[1]["type"] == "topology"
    stamps = [e["ts"] for e in events[1:]]
    assert stamps[0] == 0.0
    assert stamps == sorted(stamps)
    assert all(round(ts, 6) == ts for ts in stamps)
    assert not any("seq" in e for e in events)
    routes = [e for e in events if e["type"] == "route"]
    assert [r["ts"] for r in routes] == [61.018, 61.02, 65.12]


def test_other_fields_are_kept():
    raw, _ = read_live_recording(FYP_LIVE)
    events = convert_live_events(raw).events
    route = next(e for e in events if e["type"] == "route")
    assert route["ranked"] == [["srv1", 0.79], ["srv2", 0.77]]
    assert route["client_port"] == 40507
    assert any(e["type"] == "flow_delete" for e in events)
    nan_report = next(e for e in events if e["type"] == "report" and e["node"] == "srv3")
    assert nan_report["trust"] is None


def test_topology_goes_first_even_when_stamped_late():
    raw = [
        {"type": "switch_up", "ts": WALL_T0, "dpid": 1},
        {"type": "topology", "ts": WALL_T0 + 0.5, "graph": GRAPH},
        {"type": "route", "ts": WALL_T0 + 1.0, "chosen": "srv1"},
    ]
    events = convert_live_events(raw).events
    assert [(e["type"], e.get("ts")) for e in events] == [
        ("header", None),
        ("topology", 0.0),
        ("switch_up", 0.0),
        ("route", 1.0),
    ]
    assert validate_events(events).ok


def test_equal_stamps_keep_file_order():
    raw = [
        {"type": "topology", "ts": WALL_T0, "graph": GRAPH},
        {"type": "anomaly", "ts": WALL_T0 + 2, "node": "srv2", "signals": {"latency_tell": 2.0}},
        {"type": "node_status", "ts": WALL_T0 + 2, "nodes": {}},
    ]
    events = convert_live_events(raw).events
    assert [e["type"] for e in events[2:]] == ["anomaly", "node_status"]


def test_events_without_a_numeric_ts_are_left_out():
    raw = [
        {"type": "topology", "ts": WALL_T0, "graph": GRAPH},
        {"type": "route", "chosen": "srv1"},
        {"type": "route", "ts": "soon", "chosen": "srv1"},
        "not an object",
    ]
    conversion = convert_live_events(raw)
    assert conversion.untimed == 2
    assert conversion.skipped_lines == 1
    assert len(conversion.events) == 2


def test_nested_non_finite_values_become_null():
    raw = [
        {"type": "topology", "ts": WALL_T0, "graph": GRAPH},
        {
            "type": "node_status",
            "ts": WALL_T0 + 1,
            "nodes": {"srv1": {"trust": math.inf, "history": [1.0, math.nan]}},
        },
    ]
    conversion = convert_live_events(raw)
    assert conversion.non_finite == 2
    assert conversion.events[2]["nodes"] == {"srv1": {"trust": None, "history": [1.0, None]}}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([{"type": "header", "schema_version": "1.0", "backend": "live"}], "already starts"),
        ([{"type": "route", "ts": WALL_T0, "chosen": "srv1"}], "no topology"),
        (
            [
                {"type": "topology", "ts": WALL_T0, "graph": GRAPH},
                {"type": "topology", "ts": WALL_T0 + 300, "graph": GRAPH},
            ],
            "2 topology events",
        ),
    ],
)
def test_refuses_what_it_cannot_convert(raw, message):
    with pytest.raises(ConversionError, match=message):
        convert_live_events(raw)


def test_nothing_is_written_when_refused(tmp_path):
    source = tmp_path / "events.jsonl"
    source.write_text(json.dumps({"type": "route", "ts": WALL_T0, "chosen": "srv1"}) + "\n")
    out = tmp_path / "live.jsonl"
    with pytest.raises(ConversionError):
        convert_live_file(source, out)
    assert not out.exists()


def test_write_recording_needs_a_header(tmp_path):
    with pytest.raises(ValueError, match="header"):
        write_recording([{"type": "topology", "ts": 0.0, "graph": GRAPH}], tmp_path / "x.jsonl")


@pytest.mark.parametrize("scenario", ["both", "spoof"])
def test_a_live_shaped_run_scores_exactly_as_the_simulated_one(tmp_path, scenario):
    """The task's done-when: a live recording scores with the same commands, to the same numbers.

    A simulated run is put in the final-year controller's shape, converted
    back, and scored. Every score but the header must be identical.
    """
    sim_path = tmp_path / "sim.jsonl"
    args = ["run", "--scenario", scenario, "--seed", "2", "--duration", "60", "-q"]
    assert main([*args, "-o", str(sim_path)]) == 0
    simulated = read_events(sim_path)

    conversion = convert_live_events(livened(simulated), seed=2, strategy="zt_sdn")
    assert conversion.out_of_order == 1
    assert validate_events(conversion.events).ok
    assert conversion.events[1:] == simulated[1:]

    sim_scores = json.loads(to_json(score_recording(simulated)))
    live_scores = json.loads(to_json(score_recording(conversion.events)))
    assert live_scores.pop("recording")["backend"] == "live"
    sim_scores.pop("recording")
    assert live_scores == sim_scores
