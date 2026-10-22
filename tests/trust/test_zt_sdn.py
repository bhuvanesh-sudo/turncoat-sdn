"""The ported trust model, selector and thresholds reproduce ``zt_sdn``.

``golden_fyp_edge_score.json`` holds rows produced by the final-year project's
original ``evaluation/baseline.py`` for its two EdgeScore strategies. Driven by
the same router code (``conftest.py``), the ported calculator, selector and
thresholds must match every field to the last rounded digit. If this fails,
fix the port, never the fixture.

The detection tests are E-08 to E-11 from the project's ``tests/test_baseline.py``,
which ``tests/sim/test_simulator.py`` left to move with these components.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from turncoat_sdn.sim import SimConfig, as_rows, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

GOLDEN = json.loads((Path(__file__).parent / "golden_fyp_edge_score.json").read_text("utf-8"))
SHORT = replace(SimConfig(), sim_s=25.0, n_nodes=6)


def _run(router, scenario, seed, config=None):
    return simulate(
        router,
        scenario,
        seed,
        config=config,
        trust=SimTrustModel,
        latency_tell=latency_tell,
    )


def _row_id(row):
    return f"{row['scenario']}-{row['strategy']}-{row['seed']}"


@pytest.mark.parametrize("expected", GOLDEN["rows"], ids=_row_id)
def test_port_matches_original(expected, routers):
    run = simulate(
        routers[expected["strategy"]],
        expected["scenario"],
        expected["seed"],
        trust=SimTrustModel,
        latency_tell=latency_tell,
        name=expected["strategy"],
    )
    assert as_rows([run])[0] == expected


def test_fixture_covers_every_scenario_and_edge_score_strategy():
    rows = GOLDEN["rows"]
    assert {r["scenario"] for r in rows} == {"clean", "sybil", "drop", "both"}
    assert {r["strategy"] for r in rows} == {"no_trust", "zt_sdn"}


class TestDetection:
    """E-08 to E-11: the shipped detectors, exercised through the simulator."""

    def test_e08_zt_sdn_isolates_the_sybil(self, routers):
        """E-08: The latency tell fires and the liar stops receiving traffic."""
        zt = _run(routers["zt_sdn"], "sybil", 5, SHORT)
        rr = _run(routers["round_robin"], "sybil", 5, SHORT)
        assert zt.time_to_isolate_s is not None, "Sybil was never isolated"
        assert zt.malicious_share < rr.malicious_share / 2

    def test_e09_zt_sdn_isolates_the_dropper(self, routers):
        """E-09: The timeout-rate tell fires, and failures nearly vanish.

        Trust alone cannot do this: a node that times out every task settles
        around T = 0.36, above the 0.3 isolation line, because it still reports
        its CPU honestly. The independent tell is what closes it.
        """
        zt = _run(routers["zt_sdn"], "drop", 3, SHORT)
        rr = _run(routers["round_robin"], "drop", 3, SHORT)
        assert zt.time_to_isolate_s is not None, "dropper was never isolated"
        assert zt.failure_rate < rr.failure_rate / 2

    @pytest.mark.parametrize("scenario", ["sybil", "drop", "both"])
    def test_e10_isolation_is_prompt(self, routers, scenario):
        """E-10: Attackers are excluded within the project's <3 s isolation NFR,
        plus the poll interval it takes to observe them."""
        run = _run(routers["zt_sdn"], scenario, 9, SHORT)
        assert run.time_to_isolate_s is not None, f"{scenario}: never isolated"
        assert run.time_to_isolate_s <= 10.0

    @pytest.mark.parametrize("seed", range(30, 36))
    def test_e11_no_healthy_node_is_ever_quarantined(self, routers, seed):
        """E-11: A clean fleet is never isolated: no false positives.

        ``failed`` counts denials, so any denial here would be the system
        quarantining an honest node.
        """
        run = _run(routers["zt_sdn"], "clean", seed, SHORT)
        assert run.failed == 0, f"seed {seed}: quarantined a healthy fleet"
        assert run.time_to_isolate_s is None

    def test_zt_sdn_runs_are_reproducible(self, routers):
        """E-02 for the trust-aware path: same seed, same run."""
        first = _run(routers["zt_sdn"], "both", 11, SHORT)
        second = _run(routers["zt_sdn"], "both", 11, SHORT)
        assert first == second
