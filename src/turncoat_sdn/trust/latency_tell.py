"""The load-independent Sybil tell: a node that claims to be idle but answers slowly.

Ported unchanged from the final-year project's ``controller/flow_monitor.py``,
where these two functions sat beside the live poll loop and its ``os_ken.lib.hub``
import. The offline harness (``evaluation/baseline.py``) imported them from
there, which is how the SDN stack leaked into the simulator. Here they stand on
their own, so the live monitor and the simulator can share one implementation
without either needing os-ken.

The module satisfies :class:`turncoat_sdn.sim.LatencyTell`, so it can be passed
to the simulator as it is::

    from turncoat_sdn.sim import simulate
    from turncoat_sdn.trust import latency_tell

    result = simulate(router, "sybil", seed=1, latency_tell=latency_tell)

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import NamedTuple


class LatencyTellResult(NamedTuple):
    """Outcome of one latency-tell evaluation.

    tripped: the node should be flagged this cycle.
    strikes: the updated leaky-bucket level, to be carried into the next call.
    ratio: measured RTT as a multiple of the fleet baseline, or None when either
        figure was unavailable.
    """

    tripped: bool
    strikes: int
    ratio: float | None


def fleet_latency_baseline(rtts: Sequence[float | None]) -> float | None:
    """Median of the measured RTTs, ignoring failed probes.

    The MEDIAN, not the min: the min makes one lucky-fast poll brand every other
    node an outlier, while the median needs a majority to be honest (the standard
    assumption) and self-normalises when the whole host slows down uniformly.
    """
    measured = [r for r in rtts if r is not None]
    return statistics.median(measured) if measured else None


def evaluate_latency_tell(
    claimed_cpu: float | None,
    measured_rtt_ms: float | None,
    fleet_baseline_ms: float | None,
    strikes: int,
    idle_claim_threshold: float = 0.25,
    latency_liar_ratio: float = 3.0,
    latency_liar_floor_ms: float = 40.0,
    latency_liar_persist: int = 3,
) -> LatencyTellResult:
    """The load-independent Sybil tell, as a pure function.

    A node claiming to be (near) idle should answer its poll about as fast as the
    rest of the fleet. One burning CPU to serve slowly replies far slower no
    matter how little task traffic it receives -- the case power-of-two-choices
    routing creates, where the CPU-honesty deviation check cannot fire because
    the liar never accumulates observed load. The RTT is the controller's own
    measurement, so the node cannot understate it.

    Args:
        claimed_cpu: The node's self-reported load, or None if it sent none (in
            which case nothing is inferred -- a node is not accused of lying
            about a figure it never claimed).
        measured_rtt_ms: Controller-measured probe RTT, or None if unreachable.
        fleet_baseline_ms: Result of fleet_latency_baseline for this cycle.
        strikes: The leaky-bucket level carried over from the previous call.
        idle_claim_threshold: At or below this claimed load counts as "claims idle".
        latency_liar_ratio: How many times the baseline counts as "slow".
        latency_liar_floor_ms: Absolute gap required as well, so a fast fleet
            does not make ordinary jitter look like a multiple.
        latency_liar_persist: Strikes required before flagging.

    Returns:
        A LatencyTellResult. Persistence is a leaky bucket, not a consecutive
        counter: a strike on a slow poll, a decrement on a fast one, capped just
        above the trip level. A CPU-burner is slow nearly every poll so it fills
        and stays full (one good poll cannot clear it); transient jitter drains
        back to zero without ever filling, keeping the quarantine steady instead
        of flapping.
    """
    slow_and_idle = (
        claimed_cpu is not None
        and measured_rtt_ms is not None
        and fleet_baseline_ms is not None
        and claimed_cpu <= idle_claim_threshold
        and measured_rtt_ms > fleet_baseline_ms * latency_liar_ratio
        and (measured_rtt_ms - fleet_baseline_ms) >= latency_liar_floor_ms
    )

    if slow_and_idle:
        strikes = min(latency_liar_persist + 1, strikes + 1)
    else:
        strikes = max(0, strikes - 1)

    ratio = (
        measured_rtt_ms / fleet_baseline_ms
        if measured_rtt_ms is not None and fleet_baseline_ms
        else None
    )
    return LatencyTellResult(
        tripped=strikes >= latency_liar_persist,
        strikes=strikes,
        ratio=ratio,
    )
