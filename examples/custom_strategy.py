"""A custom strategy in under 50 lines of code: gated round robin.

Round robin is trust-blind: an attacker keeps its full share of the work. The
gated round robin keeps the strict cycle, but skips any server that the
isolation threshold or the anomaly gate holds out, the two rails ``zt_sdn``
quarantines with. It asks how much of ``zt_sdn``'s protection comes from
those rails alone, without EdgeScore's load and latency weighting.

This example runs it against ``zt_sdn`` and plain ``round_robin`` on the same
paired seeds of the ``both`` scenario (a Sybil and a blackhole), scores every
run from its recording, and tests the gaps with a paired Wilcoxon test.

Run it from the repository root:

    python examples/custom_strategy.py                        # 10 paired seeds
    python examples/custom_strategy.py --seeds 3              # quicker
    python examples/custom_strategy.py --record gated.jsonl
    turncoat score gated.jsonl

How it works, and how to write your own, is in docs/extending.md.
"""

from __future__ import annotations

import argparse

from turncoat_sdn import trust
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import EventList, EventWriter
from turncoat_sdn.sim import simulate
from turncoat_sdn.stats import paired_wilcoxon

#: The two rails zt_sdn quarantines with: the trust floor and the anomaly gate.
FLOOR, GATE = trust.DEFAULT_ISOLATION_THRESHOLD, trust.DEFAULT_ANOMALY_GATE


def gated_round_robin(n, rng):
    """A router factory: the simulator calls it once per run with the fleet size."""

    class GatedRoundRobin:
        cursor = 0  # where the cycle resumes; per run, as the factory makes a new class

        def choose(self, scores, claimed_cpu, rtt_ms, anomaly):
            # Returning None (falling off the end) refuses the task: everyone is held out.
            for k in range(n):
                i = (self.cursor + k) % n
                if scores[i] >= FLOOR and anomaly[i] < GATE:
                    self.cursor = i + 1
                    return i

    return GatedRoundRobin()


def run(strategy, seed, recorder, scenario="both"):
    """One seeded run of ``strategy`` on ``scenario``, recorded to ``recorder``."""
    hooks = {"trust": trust.SimTrustModel, "latency_tell": trust.latency_tell, "recorder": recorder}
    simulate(STRATEGIES.get(strategy, gated_round_robin), scenario, seed, name=strategy, **hooks)


def main(seeds: int, record: str | None) -> None:
    print(f"gated_rr against two built-ins on 'both' (a Sybil and a blackhole), {seeds} seeds\n")
    rows = []
    for strategy in ("gated_rr", "zt_sdn", "round_robin"):
        for seed in range(1, seeds + 1):
            recording = EventList(backend="sim", seed=seed, strategy=strategy, scenario="both")
            run(strategy, seed, recording)
            service = score_recording(recording.events)["service"]
            rows.append({"strategy": strategy, "scenario": "both", "seed": seed, **service})
    for metric in ("slo_violation_rate", "failure_rate"):
        for rival in ("zt_sdn", "round_robin"):
            test = paired_wilcoxon(rows, "gated_rr", rival, "both", metric)
            mean = sum(r[metric] for r in rows if r["strategy"] == rival) / seeds
            print(
                f"  {metric:<19} gated_rr {mean + test.mean_difference:6.2%}  vs  "
                f"{rival:<11} {mean:6.2%}  (Wilcoxon p = {test.p_value:.4f})"
            )
    if record:
        with EventWriter(record, backend="sim", seed=1, strategy="gated_rr") as rec:
            run("gated_rr", 1, rec)
        print(f"\nRecorded seed 1 to {record}. Next: turncoat score {record}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run gated round robin, a custom strategy.")
    parser.add_argument("--seeds", type=int, default=10, help="paired seeds (default 10)")
    parser.add_argument("--record", metavar="PATH", help="also record one run to this file")
    args = parser.parse_args()
    main(args.seeds, args.record)
