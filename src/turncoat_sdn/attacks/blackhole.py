"""Blackhole: accepts every task and drops all of them.

Moved out of the simulator's event loop (the final-year project's
``evaluation/baseline.py``), where it was the ``role == "drop"`` branch. Once
it turns, every task it accepts holds a worker and never completes, so the
client times out. It still answers polls promptly and reports its load
honestly, which is why trust alone floors at about 0.36 and the timeout-rate
tell is what isolates it.

Its ground-truth label stays ``drop``, the name the simulator and the
project's node agent always used, so recordings and scores from earlier
releases still compare. The attack scorer reports ``drop`` as ``blackhole``.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import random

from turncoat_sdn.attacks.base import ServerAttack


class Blackhole(ServerAttack):
    """Drops every task it accepts, from ``start_s`` on.

    Args:
        start_s: Simulated second at which it starts dropping.
    """

    name = "drop"

    def serve(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        return None
