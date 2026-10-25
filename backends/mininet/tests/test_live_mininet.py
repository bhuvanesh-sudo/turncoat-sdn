"""A real run on Mininet, from the guide. Needs Linux, root, Open vSwitch and Mininet.

Marked ``live``: it skips itself anywhere it cannot run, so core CI and every
laptop without the testbed pass without it. On the testbed, run it with::

    sudo .venv/bin/python -m pytest -m live backends/mininet/tests
"""

from __future__ import annotations

import os
import shutil

import pytest
from turncoat_mininet import run, topology

from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not topology.mininet_available(), reason="Mininet is not installed"),
    pytest.mark.skipif(
        not hasattr(os, "geteuid") or os.geteuid() != 0, reason="Mininet needs root"
    ),
    pytest.mark.skipif(shutil.which("ovs-vsctl") is None, reason="Open vSwitch is not installed"),
]


def test_a_sybil_run_on_mininet_validates_and_names_the_sybil(tmp_path):
    out = tmp_path / "live.jsonl"
    code = run.main(
        [
            "--network",
            "mininet",
            "--scenario",
            "sybil",
            "--onset",
            "10",
            "--duration",
            "40",
            "--logs",
            str(tmp_path / "logs"),
            "-o",
            str(out),
        ]
    )
    assert code == 0
    report = validate_file(out)
    assert report.ok, report.format(str(out))
    events = read_events(out)
    assert events[0]["network"] == "mininet"
    verdicts = {r.subject: r.predicted for r in score_run(events)}
    assert verdicts["srv4"] == "sybil"
