"""A custom turncoat in under 50 lines of code: the slowpoke.

From its onset, the slowpoke serves every task it accepts, but four times
slower, and it reports its load honestly. It drops nothing and never lies, so
the signals the trust model is built on (task success and honest reporting)
barely move: only the rare long task that now outlasts the client's timeout
fails. This example plugs it into the simulator, scores every run from its
recording, and asks two questions over paired seeds: does any defence
quarantine it, and what does it cost?

Run it from the repository root:

    python examples/custom_attack.py                        # 10 paired seeds
    python examples/custom_attack.py --seeds 3              # quicker
    python examples/custom_attack.py --record slowpoke.jsonl
    turncoat score slowpoke.jsonl

How it works, and how to write your own, is in docs/extending.md.
"""

from __future__ import annotations

import argparse

from turncoat_sdn.attacks import ServerAttack
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import EventList, EventWriter
from turncoat_sdn.sim import simulate
from turncoat_sdn.stats import paired_wilcoxon
from turncoat_sdn.trust import SimTrustModel, latency_tell


class Slowpoke(ServerAttack):
    """Serves every task ``slowdown`` times slower from ``start_s`` on, and never lies."""

    name = "slowpoke"  # the ground-truth label written into the recording

    def __init__(self, start_s: float = 0.0, *, slowdown: float = 4.0) -> None:
        super().__init__(start_s)
        self.slowdown = slowdown

    def serve(self, now, demand_s, rng):
        return demand_s * self.slowdown  # late, but it answers


#: srv8 (node index 7) turns at 30 s. One instance can serve every run.
SLOWPOKE = {7: Slowpoke(start_s=30.0)}


def run(strategy, seed, attacks, recorder):
    """One seeded run of the clean fleet with ``attacks`` placed, recorded to ``recorder``."""
    hooks = {"trust": SimTrustModel, "latency_tell": latency_tell, "recorder": recorder}
    simulate(STRATEGIES[strategy], "clean", seed, attacks=attacks, name=strategy, **hooks)


def main(seeds: int, record: str | None) -> None:
    print(f"Slowpoke on srv8 from 30 s, {seeds} paired seeds\n")
    for strategy in ("zt_sdn", "least_conn"):
        rows, quarantined = [], 0
        for seed in range(1, seeds + 1):
            for label, attacks in (("honest", {}), ("slowpoke", SLOWPOKE)):
                recording = EventList(backend="sim", seed=seed, strategy=strategy, scenario=label)
                run(strategy, seed, attacks, recording)
                scores = score_recording(recording.events)
                slo = scores["service"]["slo_violation_rate"]
                rows.append({"strategy": label, "scenario": "clean", "seed": seed, "slo": slo})
                quarantined += scores["detection"]["attackers_quarantined"]
        test = paired_wilcoxon(rows, "slowpoke", "honest", "clean", "slo")
        honest = sum(r["slo"] for r in rows if r["strategy"] == "honest") / seeds
        print(
            f"  {strategy:<11} SLO violations {honest:6.2%} -> {honest + test.mean_difference:6.2%}"
            f"  (Wilcoxon p = {test.p_value:.4f}); quarantined in {quarantined} of {seeds} runs"
        )
    if record:
        with EventWriter(record, backend="sim", seed=1, strategy="zt_sdn") as recorder:
            run("zt_sdn", 1, SLOWPOKE, recorder)
        print(f"\nRecorded seed 1 under zt_sdn to {record}. Next: turncoat score {record}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the slowpoke, a custom turncoat.")
    parser.add_argument("--seeds", type=int, default=10, help="paired seeds (default 10)")
    parser.add_argument("--record", metavar="PATH", help="also record one run to this file")
    args = parser.parse_args()
    main(args.seeds, args.record)
