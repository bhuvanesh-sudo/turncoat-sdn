"""On-off: a Sybil that alternates hostile and honest phases.

Once it turns at ``start_s``, it spends ``on_s`` seconds behaving exactly like
the Sybil (claims to be idle, serves slowly, answers polls slowly), then
``off_s`` seconds behaving honestly, and repeats. The honest phases let its
anomaly level drain and its quarantine lift, so it earns its way back into
rotation before the next hostile phase.

The hostile phase lies rather than drops on purpose. The attack classifier
tells on-off from its sibling by INTERMITTENCY within the load-dishonesty
family: a liar that goes measurably honest between phases is ``onoff``, a
steady one is ``sybil``. An attacker that dropped tasks in its hostile phases
would be scored in the dropping family, as a grayhole or blackhole.

The phase is a pure function of ``now``, so the attack draws no random numbers
and keeps no per-run state: the same seed gives the same run, and the paired
workload never moves.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import random

from turncoat_sdn.attacks.base import Status
from turncoat_sdn.attacks.sybil import Sybil

#: Default phase lengths, in seconds: a 20 s period at half duty. Each honest
#: phase is well past the classifier's ``ONOFF_MIN_GOOD_PHASE_S`` (about 4 s),
#: and a 120 s run holds six periods, three times what its replay window needs.
DEFAULT_ON_S = 10.0
DEFAULT_OFF_S = 10.0


def _positive(name: str, value: float) -> float:
    if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a finite number of seconds > 0, got {value!r}")
    return float(value)


class OnOff(Sybil):
    """Lies like a Sybil for ``on_s``, is honest for ``off_s``, from ``start_s`` on.

    Args:
        start_s: Simulated second of the first hostile phase.
        on_s: Length of each hostile phase.
        off_s: Length of each honest phase between them.
        claimed_cpu: The load it claims while hostile, as for :class:`Sybil`.
        slowdown: Service-time multiplier while hostile, as for :class:`Sybil`.
        rtt_ms: How slowly it answers polls while hostile, before jitter.
    """

    name = "onoff"

    def __init__(
        self,
        start_s: float = 0.0,
        *,
        on_s: float = DEFAULT_ON_S,
        off_s: float = DEFAULT_OFF_S,
        claimed_cpu: float = 0.1,
        slowdown: float = 2.0,
        rtt_ms: float = 220.0,
    ) -> None:
        super().__init__(start_s, claimed_cpu=claimed_cpu, slowdown=slowdown, rtt_ms=rtt_ms)
        self.on_s = _positive("on_s", on_s)
        self.off_s = _positive("off_s", off_s)

    def hostile(self, now: float) -> bool:
        """Whether ``now`` falls in a hostile phase. Always False before the onset."""
        if not self.active(now):
            return False
        return (now - self.start_s) % (self.on_s + self.off_s) < self.on_s

    def serve(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        if not self.hostile(now):
            return demand_s
        return super().serve(now, demand_s, rng)

    def report(self, now: float, honest: Status, jitter_ms: float, rng: random.Random) -> Status:
        if not self.hostile(now):
            return honest
        return super().report(now, honest, jitter_ms, rng)

    def __repr__(self) -> str:
        return (
            f"OnOff(start_s={self.start_s:g}, on_s={self.on_s:g}, off_s={self.off_s:g}, "
            f"claimed_cpu={self.claimed_cpu:g}, slowdown={self.slowdown:g}, rtt_ms={self.rtt_ms:g})"
        )
