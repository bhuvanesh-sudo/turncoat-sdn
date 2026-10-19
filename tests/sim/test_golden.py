"""The port reproduces the final-year project's numbers exactly.

``golden_fyp_baseline.json`` holds rows produced by the original
``evaluation/baseline.py`` with its default settings. The ported simulator,
driven by the same trust-blind routers, must match every field to the last
rounded digit. If this fails, fix the port, never the fixture.

``time_to_isolate_s`` is left out: the original computed it with the real trust
calculator and latency tell, which arrive in ``turncoat_sdn.trust``. Routing by
these three strategies never reads trust or anomaly, so every other field is
unaffected by their absence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from turncoat_sdn.sim import as_rows, simulate

GOLDEN = json.loads((Path(__file__).parent / "golden_fyp_baseline.json").read_text("utf-8"))
NOT_COMPARED = {"time_to_isolate_s"}


def _row_id(row):
    return f"{row['scenario']}-{row['strategy']}-{row['seed']}"


@pytest.mark.parametrize("expected", GOLDEN["rows"], ids=_row_id)
def test_port_matches_original(expected, routers):
    run = simulate(
        routers[expected["strategy"]],
        expected["scenario"],
        expected["seed"],
        name=expected["strategy"],
    )
    got = as_rows([run])[0]
    for key in NOT_COMPARED:
        got.pop(key)
    want = {k: v for k, v in expected.items() if k not in NOT_COMPARED}
    assert got == want


def test_fixture_covers_every_scenario_and_router(routers):
    rows = GOLDEN["rows"]
    assert {r["scenario"] for r in rows} == {"clean", "sybil", "drop", "both"}
    assert {r["strategy"] for r in rows} == set(routers)
