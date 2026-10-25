"""The live recording check: a live run is graded by the same commands as a simulated one.

One loopback run (real agent and client processes on 127.0.0.1, the real
controller) is recorded, then put through ``turncoat validate`` and
``turncoat score`` exactly as a user would, and its events are compared field
by field with a simulated run of the same scenario. Every field the simulator
records, the live run records too, so no scorer has a live-only code path.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from turncoat_mininet import topology

from turncoat_sdn.cli import main
from turncoat_sdn.events import read_events

SCENARIO = "both"
SERVERS = 4


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_run(tmp_path_factory) -> Path:
    """One short loopback run with a blackhole and a Sybil, shared by every test here."""
    tmp = tmp_path_factory.mktemp("live")
    out = tmp / "live.jsonl"
    argv = [
        "--network",
        "loopback",
        "--scenario",
        SCENARIO,
        "--servers",
        str(SERVERS),
        "--clients",
        "4",
        "--duration",
        "10",
        "--api-port",
        str(_free_port()),
        "--agent-base-port",
        str(_free_port() + 100),
        "--logs",
        str(tmp / "logs"),
        "-o",
        str(out),
    ]
    result = subprocess.run(
        [sys.executable, "-m", "turncoat_mininet.run", *argv],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(topology.BACKEND_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="module")
def sim_run(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sim") / "sim.jsonl"
    assert main(["run", "--scenario", SCENARIO, "--duration", "30", "-q", "-o", str(out)]) == 0
    return out


def _fields_by_type(path: Path) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = defaultdict(set)
    for event in read_events(path):
        fields[event["type"]] |= set(event)
    return fields


def test_turncoat_validate_passes_the_live_recording(live_run, capsys):
    assert main(["validate", str(live_run)]) == 0
    assert "valid, schema 1.0" in capsys.readouterr().out


def test_turncoat_score_grades_the_live_recording(live_run, capsys):
    assert main(["score", str(live_run), "--json"]) == 0
    scores = json.loads(capsys.readouterr().out)
    assert scores["recording"]["backend"] == "live"
    assert scores["service"]["offered"] > 0
    truth = {s["subject"]: s["truth"] for s in scores["subjects"] if s["kind"] == "node"}
    assert sorted(truth.values()).count("none") == SERVERS - 2
    assert {"blackhole", "sybil"} <= set(truth.values())


def test_the_summary_prints_like_a_simulated_one(live_run, sim_run, capsys):
    assert main(["score", str(sim_run)]) == 0
    simulated = capsys.readouterr().out
    assert main(["score", str(live_run)]) == 0
    live = capsys.readouterr().out
    assert "(live backend" in live
    sections = ("Service", "Attackers", "Detection:")
    for section in sections:
        assert section in simulated and section in live


def test_live_events_carry_every_field_the_simulator_records(live_run, sim_run):
    live = _fields_by_type(live_run)
    simulated = _fields_by_type(sim_run)
    for event_type in ("topology", "route", "report", "anomaly", "node_status", "quarantine"):
        assert event_type in live, f"the live run recorded no {event_type}"
        missing = simulated[event_type] - live[event_type]
        assert not missing, f"live {event_type} events lack {sorted(missing)}"


def test_client_outcomes_are_reports_in_the_shared_shape(live_run):
    """The IoT clients write nothing themselves: their outcomes reach the recording as reports."""
    reports = [e for e in read_events(live_run) if e["type"] == "report"]
    assert reports
    devices = {e["device"] for e in reports}
    assert devices and all(d.startswith("iot") for d in devices)
    assert {e["status"] for e in reports} <= {"success", "timeout", "failure"}
