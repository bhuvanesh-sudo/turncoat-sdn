"""The CLI's five strategies reproduce the final-year project's numbers.

``turncoat run`` must give the same answer as the code the golden-file tests
already pin, so these drive :data:`STRATEGIES` against both golden files:
``tests/sim/golden_fyp_baseline.json`` (the trust-blind routers) and
``tests/trust/golden_fyp_edge_score.json`` (``no_trust`` and ``zt_sdn``). If
this fails, fix the router, never the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from turncoat_sdn.cli.routers import DESCRIPTIONS, STRATEGIES
from turncoat_sdn.sim import as_rows, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

TESTS = Path(__file__).parent.parent
BLIND = json.loads((TESTS / "sim" / "golden_fyp_baseline.json").read_text("utf-8"))["rows"]
EDGE = json.loads((TESTS / "trust" / "golden_fyp_edge_score.json").read_text("utf-8"))["rows"]


def _row_id(row):
    return f"{row['scenario']}-{row['strategy']}-{row['seed']}"


def test_the_five_strategies_of_the_plan():
    assert set(STRATEGIES) == {"random", "round_robin", "least_conn", "no_trust", "zt_sdn"}
    assert set(DESCRIPTIONS) == set(STRATEGIES)


@pytest.mark.parametrize("expected", BLIND, ids=_row_id)
def test_trust_blind_strategies_match_the_project(expected):
    # The golden rows were made without the trust hooks, which these routers
    # never read; only time_to_isolate_s depends on them.
    run = simulate(
        STRATEGIES[expected["strategy"]],
        expected["scenario"],
        expected["seed"],
        name=expected["strategy"],
    )
    got = as_rows([run])[0]
    got.pop("time_to_isolate_s")
    want = {k: v for k, v in expected.items() if k != "time_to_isolate_s"}
    assert got == want


@pytest.mark.parametrize("expected", EDGE, ids=_row_id)
def test_edge_score_strategies_match_the_project(expected):
    run = simulate(
        STRATEGIES[expected["strategy"]],
        expected["scenario"],
        expected["seed"],
        trust=SimTrustModel,
        latency_tell=latency_tell,
        name=expected["strategy"],
    )
    assert as_rows([run])[0] == expected


def test_both_fixtures_together_cover_every_strategy():
    assert {r["strategy"] for r in BLIND + EDGE} == set(STRATEGIES)
