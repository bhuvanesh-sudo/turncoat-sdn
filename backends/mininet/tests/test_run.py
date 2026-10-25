"""``python -m turncoat_mininet.run``: options, guard clauses and a real loopback run.

The loopback run starts real agent and client processes on 127.0.0.1 and runs
the real controller for a few seconds, so it covers every live code path a
Mininet run uses except the emulated links. Its recording must validate and
score with the core tools, unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from turncoat_mininet import run, topology

from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run


class TestOptions:
    def test_defaults(self):
        args = run.build_parser().parse_args([])
        assert (args.network, args.strategy, args.scenario) == ("mininet", "zt_sdn", "sybil")
        assert (args.servers, args.clients, args.duration) == (4, 12, 60.0)

    def test_attackers_are_placed_like_turncoat_run(self):
        args = run.build_parser().parse_args(
            ["--scenario", "both", "--onset", "15", "--attack", "grayhole,node=srv1,start=5"]
        )
        attacks = run.place(args, run.build_config(args))
        assert {i: (a.name, a.start_s) for i, a in attacks.items()} == {
            0: ("grayhole", 5.0),
            2: ("drop", 15.0),
            3: ("sybil", 15.0),
        }

    def test_load_sets_the_arrival_rate(self):
        args = run.build_parser().parse_args(["--servers", "2", "--load", "0.5"])
        assert run.build_config(args).arrival_rate == pytest.approx(20.0)

    def test_client_attacks_are_refused_for_now(self, capsys):
        assert run.main(["--network", "loopback", "--scenario", "spoof"]) == 2
        assert "not supported by the live backend" in capsys.readouterr().err

    def test_a_bad_attack_spec_is_a_usage_error(self, capsys):
        assert run.main(["--attack", "wormhole"]) == 2
        assert "unknown attack" in capsys.readouterr().err


class TestMininetGuards:
    def test_mininet_network_needs_root_or_mininet(self, capsys, tmp_path, monkeypatch):
        if topology.mininet_available() and getattr(os, "geteuid", lambda: 1)() == 0:
            pytest.skip("this machine could really run Mininet")
        code = run.main(["--network", "mininet", "-o", str(tmp_path / "x.jsonl")])
        assert code == 1
        err = capsys.readouterr().err
        assert "needs root" in err or "Mininet is not importable" in err


def test_a_run_that_cannot_start_in_time_refuses_to_run(tmp_path, free_port, capsys):
    code = run.main(
        [
            "--network",
            "loopback",
            "--servers",
            "1",
            "--clients",
            "1",
            "--warmup",
            "0",
            "--api-port",
            str(free_port()),
            "--agent-base-port",
            str(free_port() + 100),
            "--logs",
            str(tmp_path / "logs"),
            "-o",
            str(tmp_path / "x.jsonl"),
        ]
    )
    assert code == 1
    error = capsys.readouterr().err
    assert "not ready by the start" in error or "agents not answering by the start" in error


def test_loopback_run_records_a_valid_scorable_run(tmp_path, free_port):
    out = tmp_path / "live.jsonl"
    argv = [
        "--network",
        "loopback",
        "--scenario",
        "drop",
        "--servers",
        "3",
        "--clients",
        "3",
        "--duration",
        "8",
        "--api-port",
        str(free_port()),
        "--agent-base-port",
        str(free_port() + 100),
        "--logs",
        str(tmp_path / "logs"),
        "-o",
        str(out),
    ]
    result = subprocess.run(
        [sys.executable, "-m", "turncoat_mininet.run", *argv],
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "PYTHONPATH": str(topology.BACKEND_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["offered"] > 50
    assert summary["completed"] > 0

    report = validate_file(out)
    assert report.ok, report.format(str(out))
    events = read_events(out)
    assert events[0]["backend"] == "live"
    assert events[0]["network"] == "loopback"
    truth = {n["id"]: n["attack"] for n in events[1]["graph"]["nodes"] if n["kind"] == "server"}
    assert truth == {"srv1": "none", "srv2": "none", "srv3": "drop"}
    # The blackhole really dropped: its tasks timed out on the clients.
    timeouts = [e for e in events if e["type"] == "report" and e["status"] == "timeout"]
    assert timeouts and {e["node"] for e in timeouts} == {"srv3"}
    assert any(e["type"] == "node_status" for e in events)
    scored = {r.subject: r for r in score_run(events)}
    assert scored["srv3"].truth == "blackhole"
