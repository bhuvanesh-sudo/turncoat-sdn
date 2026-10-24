"""Sybil, the load liar: claims to be idle to attract work it then serves slowly.

Moved out of the simulator's event loop (the final-year project's
``evaluation/baseline.py``), where it was a pair of ``if role == "sybil"``
branches. The behaviour and defaults are unchanged: once it turns, it reports
a load of 0.1 whatever the truth, serves every task at half speed because it
burns CPU, and answers polls at 220 ms against a healthy 50 ms. That slow
answer is what the latency tell catches.

It never fails a task. Its trust score stays high, which is why the anomaly
gate, not the trust formula, has to catch it (see ``docs/trust-model.md``).

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import random

from turncoat_sdn.attacks.base import ServerAttack, Status


class Sybil(ServerAttack):
    """Lies about its load and serves slowly, from ``start_s`` on.

    Args:
        start_s: Simulated second at which it starts lying.
        claimed_cpu: The load it claims once it turns, whatever the truth.
        slowdown: Service-time multiplier once it turns. Keep it below 2.5:
            past that the Sybil cannot absorb its fair share at the default
            load, its backlog times out, and it becomes a failing node that
            trust isolates on its own, which is a much easier attack.
        rtt_ms: How slowly it answers polls once it turns, before jitter.
    """

    name = "sybil"

    def __init__(
        self,
        start_s: float = 0.0,
        *,
        claimed_cpu: float = 0.1,
        slowdown: float = 2.0,
        rtt_ms: float = 220.0,
    ) -> None:
        super().__init__(start_s)
        if not 0.0 <= claimed_cpu <= 1.0:
            raise ValueError(f"claimed_cpu must be between 0 and 1, got {claimed_cpu}")
        if slowdown <= 0:
            raise ValueError(f"slowdown must be positive, got {slowdown}")
        if rtt_ms < 0:
            raise ValueError(f"rtt_ms must not be negative, got {rtt_ms}")
        self.claimed_cpu = claimed_cpu
        self.slowdown = slowdown
        self.rtt_ms = rtt_ms

    def serve(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        return demand_s * self.slowdown

    def report(self, now: float, honest: Status, jitter_ms: float, rng: random.Random) -> Status:
        return Status(self.claimed_cpu, self.rtt_ms + jitter_ms)

    def __repr__(self) -> str:
        return (
            f"Sybil(start_s={self.start_s:g}, claimed_cpu={self.claimed_cpu:g}, "
            f"slowdown={self.slowdown:g}, rtt_ms={self.rtt_ms:g})"
        )
