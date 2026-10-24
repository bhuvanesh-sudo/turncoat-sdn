"""Grayhole: accepts every task and drops a fraction of them.

A selective blackhole. Once it turns, each task it accepts is dropped with
probability ``drop_fraction``: it holds the worker and never answers, so the
client times out, exactly as with the blackhole. The rest it serves honestly.
It answers polls promptly and reports its load honestly.

Its losses are partial, so its timeout rate sits between an honest node's and
a blackhole's. The timeout-rate tell catches it once that rate passes
``honesty_deviation_threshold`` (0.40), and the attack classifier names it
``grayhole`` rather than ``blackhole`` because the median rate stays under the
0.85 blackhole bar.

Whether each task is dropped is drawn from the attacker's own seeded stream,
one draw per task after the onset, so the same seed drops the same tasks and
the workload the strategies are paired on never moves.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import random

from turncoat_sdn.attacks.base import ServerAttack

#: Default share of tasks dropped after the onset. A dropped task holds its
#: worker until the client times out, so tasks queued behind it give up too
#: and the observed timeout rate runs above the fraction (about 0.6 at 0.5).
#: That is high enough for the timeout-rate tell (0.40) to fire reliably and
#: low enough for the classifier's median rate to stay under the 0.85
#: blackhole bar.
DEFAULT_DROP_FRACTION = 0.5


class Grayhole(ServerAttack):
    """Drops a fraction of the tasks it accepts, from ``start_s`` on.

    Args:
        start_s: Simulated second at which it starts dropping.
        drop_fraction: Probability that a task accepted after the onset is
            dropped, 0 to 1. 0 serves everything honestly; 1 drops everything,
            like a blackhole, though it is still labelled ``grayhole``.
    """

    name = "grayhole"

    def __init__(
        self, start_s: float = 0.0, *, drop_fraction: float = DEFAULT_DROP_FRACTION
    ) -> None:
        super().__init__(start_s)
        if not (
            isinstance(drop_fraction, (int, float))
            and math.isfinite(drop_fraction)
            and 0.0 <= drop_fraction <= 1.0
        ):
            raise ValueError(f"drop_fraction must be between 0 and 1, got {drop_fraction!r}")
        self.drop_fraction = float(drop_fraction)

    def serve(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        # Always one draw per task, so the stream stays aligned whatever the fraction.
        if rng.random() < self.drop_fraction:
            return None
        return demand_s

    def __repr__(self) -> str:
        return f"Grayhole(start_s={self.start_s:g}, drop_fraction={self.drop_fraction:g})"
