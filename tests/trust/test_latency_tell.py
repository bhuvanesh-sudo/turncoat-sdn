"""The latency tell, moved out of ``controller/flow_monitor.py`` without the os-ken import.

The final-year project tested these functions through ``FlowMonitor._poll_once``,
which needs os-ken. The scenarios below are the same ones from its
``tests/test_flow_monitor.py`` and ``tests/test_inventory.py``, driven straight
through the pure functions the way the poll loop called them: one fleet
baseline per poll, then one evaluation per node with its strikes carried over.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import (
    LatencyTellResult,
    evaluate_latency_tell,
    fleet_latency_baseline,
    latency_tell,
)

GOLDEN = json.loads(
    (Path(__file__).parent.parent / "sim" / "golden_fyp_baseline.json").read_text("utf-8")
)


def _poll(fleet, polls):
    """Run the tell over ``polls`` cycles of a fixed fleet.

    ``fleet`` maps node name to ``(claimed_cpu, rtt_ms)``. Returns the last
    result for every node.
    """
    strikes = dict.fromkeys(fleet, 0)
    last = {}
    for _ in range(polls):
        baseline = fleet_latency_baseline([rtt for _, rtt in fleet.values()])
        for node, (claimed, rtt) in fleet.items():
            last[node] = evaluate_latency_tell(claimed, rtt, baseline, strikes[node])
            strikes[node] = last[node].strikes
    return last


class TestFleetBaseline:
    def test_is_the_median_not_the_min(self):
        # One lucky-fast poll must not make the rest of the fleet look slow.
        assert fleet_latency_baseline([5.0, 20.0, 21.0, 22.0, 150.0]) == 21.0

    def test_ignores_failed_probes(self):
        assert fleet_latency_baseline([20.0, None, 22.0, None, 24.0]) == 22.0

    def test_is_none_when_every_probe_failed(self):
        assert fleet_latency_baseline([None, None]) is None
        assert fleet_latency_baseline([]) is None


class TestLatencyTell:
    def test_catches_a_sybil_that_claims_idle_but_answers_slowly(self):
        """srv3 claims 0.1 load but answers ~7x slower than the fleet median."""
        fleet = {
            "srv1": (0.1, 20.0),
            "srv2": (0.1, 20.0),
            "srv3": (0.1, 150.0),
            "srv4": (0.1, 20.0),
        }
        # Persistence guards against a single blip: not caught on poll one or two.
        assert not _poll(fleet, 1)["srv3"].tripped
        assert not _poll(fleet, 2)["srv3"].tripped
        last = _poll(fleet, 3)
        assert last["srv3"].tripped
        assert last["srv3"].ratio == pytest.approx(7.5)
        assert not any(last[n].tripped or last[n].strikes for n in ("srv1", "srv2", "srv4"))

    def test_ignores_fast_idle_nodes(self):
        fleet = {
            "srv1": (0.05, 18.0),
            "srv2": (0.10, 22.0),
            "srv3": (0.08, 25.0),
            "srv4": (0.10, 20.0),
        }
        last = _poll(fleet, 5)
        assert not any(r.tripped or r.strikes for r in last.values())

    def test_ignores_transient_jitter(self):
        """A node slow on every other poll drains back down and never trips."""
        strikes = 0
        for i in range(6):
            rtt = 200.0 if i % 2 == 0 else 20.0
            baseline = fleet_latency_baseline([20.0, rtt, 20.0, 20.0])
            result = evaluate_latency_tell(0.1, rtt, baseline, strikes)
            strikes = result.strikes
            assert not result.tripped
        assert strikes == 0

    def test_ignores_a_slow_node_that_admits_it_is_busy(self):
        """Slow but claiming high load is consistent, not a lie."""
        fleet = {
            "srv1": (0.1, 20.0),
            "srv2": (0.1, 20.0),
            "srv3": (0.7, 150.0),
            "srv4": (0.1, 20.0),
        }
        last = _poll(fleet, 5)
        assert not last["srv3"].tripped
        assert last["srv3"].strikes == 0

    def test_one_good_poll_does_not_clear_a_full_bucket(self):
        strikes = 0
        for _ in range(10):
            strikes = evaluate_latency_tell(0.1, 150.0, 20.0, strikes).strikes
        assert strikes == 4  # capped just above the trip level of 3
        recovered = evaluate_latency_tell(0.1, 20.0, 20.0, strikes)
        assert recovered.tripped
        assert recovered.strikes == 3

    def test_needs_an_absolute_gap_as_well_as_a_ratio(self):
        # 6x a fast fleet, but only 25 ms slower: ordinary jitter, not a liar.
        result = evaluate_latency_tell(0.1, 30.0, 5.0, 0)
        assert result.strikes == 0
        assert result.ratio == pytest.approx(6.0)

    @pytest.mark.parametrize(
        ("claimed", "rtt", "baseline"),
        [(None, 150.0, 20.0), (0.1, None, 20.0), (0.1, 150.0, None)],
        ids=["no-claim", "unreachable", "no-baseline"],
    )
    def test_missing_figures_never_count_as_a_strike(self, claimed, rtt, baseline):
        result = evaluate_latency_tell(claimed, rtt, baseline, 2)
        assert result.strikes == 1
        if rtt is None or baseline is None:
            assert result.ratio is None

    def test_fleet_median_accuses_a_slow_but_honest_hardware_class(self):
        """Known limit of the fleet baseline, from ``test_inventory.py``.

        With mostly fast NUCs, an honest Raspberry Pi at 60 ms is five times the
        fleet median and gets flagged. The live monitor fixes this with
        per-class baselines; the simulator's fleet is uniform, so it does not
        need them.
        """
        rtts = [60.0, 64.0, 250.0, 10.0, 12.0, 11.0, 10.0, 12.0]
        baseline = fleet_latency_baseline(rtts)
        assert baseline == 12.0
        strikes = 0
        for _ in range(3):
            strikes = evaluate_latency_tell(0.1, 60.0, baseline, strikes).strikes
        assert strikes >= 3

    def test_returns_a_named_tuple(self):
        result = evaluate_latency_tell(0.1, 20.0, 20.0, 0)
        assert isinstance(result, LatencyTellResult)
        assert result == (False, 0, 1.0)


def _round_robin(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


@pytest.mark.parametrize(
    "expected",
    [r for r in GOLDEN["rows"] if r["strategy"] == "round_robin" and r["scenario"] != "clean"],
    ids=lambda r: f"{r['scenario']}-{r['seed']}",
)
def test_simulator_isolates_attackers_when_the_original_did(expected):
    """The module plugs into the simulator's hook as it is.

    ``tests/sim/test_golden.py`` leaves ``time_to_isolate_s`` out because it
    needs the latency tell. With the tell in place, the first moment every
    attacker is excluded matches the final-year project's numbers.
    """
    run = simulate(_round_robin, expected["scenario"], expected["seed"], latency_tell=latency_tell)
    assert run.time_to_isolate_s == pytest.approx(expected["time_to_isolate_s"])
