"""The interfaces the simulator calls into.

The final-year harness imported the routing selector, the trust calculator and
the latency tell directly from the controller, which dragged os-ken in with
them. Here they are hooks: the simulator owns the network, the clients and the
attackers, and anything that makes a controller decision is passed in.

Each hook is a :class:`typing.Protocol`, so any object with the right methods
fits. No base class is needed.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class Router(Protocol):
    """Picks the node that serves each arriving task. One instance per run."""

    def choose(
        self,
        trust: Sequence[float],
        claimed_cpu: Sequence[float],
        rtt_ms: Sequence[float],
        anomaly: Sequence[float],
    ) -> int | None:
        """Return the chosen node index, or ``None`` to refuse the task.

        The four sequences are the controller's view at the moment of the
        arrival, indexed by node: trust score, self-reported load (0 to 1),
        measured ``/status`` RTT and smoothed anomaly level (0 to 1). They are
        live views, so a router must not keep or mutate them.

        Returning ``None`` means every node was quarantined. The task is denied
        and counts as a failure and an SLO violation.
        """
        ...


#: Builds a fresh router for one run from the node count and its own seeded
#: random stream. Draw all randomness from that stream, or runs stop pairing.
RouterFactory = Callable[[int, random.Random], Router]


@dataclass(frozen=True)
class Outcome:
    """One finished task, as the trust model sees it.

    The field names match the final-year project's ``TrustUpdate`` so an
    adapter around ``TrustCalculator`` is a direct copy.
    """

    node: int
    """Index of the node that held the task."""
    edge_node_id: str
    """Stable node name, ``srv1`` to ``srvN``."""
    timestamp: float
    """Simulated time of completion or timeout, in seconds."""
    task_status: Literal["success", "timeout"]
    cpu_usage: float
    """The node's true occupancy (0 to 1) right after the task left."""
    reported_cpu: float
    """What the node last claimed its load was."""
    latency_ms: float
    """Time from arrival to completion or timeout."""
    anomaly_flag: bool
    """Whether the node's anomaly level is at or above the gate."""


class TrustModel(Protocol):
    """Turns task outcomes into a per-node trust score. One instance per run."""

    @property
    def initial_score(self) -> float:
        """Trust every node starts with."""
        ...

    def update(self, outcome: Outcome) -> float:
        """Record one outcome and return the node's new trust score."""
        ...


#: Builds a fresh trust model for one run.
TrustModelFactory = Callable[[], TrustModel]


class TellResult(Protocol):
    """What one latency-tell evaluation returns."""

    @property
    def tripped(self) -> bool: ...

    @property
    def strikes(self) -> int: ...


class LatencyTell(Protocol):
    """The load-independent Sybil tell, evaluated once per node per poll.

    A module that defines these two functions satisfies the protocol, so the
    functions moved out of the project's ``controller/flow_monitor.py`` can be
    passed in as they are.
    """

    def fleet_latency_baseline(self, rtts: Sequence[float]) -> float | None:
        """Return the fleet's reference RTT for this poll."""
        ...

    def evaluate_latency_tell(
        self,
        claimed_cpu: float,
        measured_rtt_ms: float,
        fleet_baseline_ms: float | None,
        strikes: int,
    ) -> TellResult:
        """Decide whether one node looks like a liar, carrying ``strikes`` forward."""
        ...
