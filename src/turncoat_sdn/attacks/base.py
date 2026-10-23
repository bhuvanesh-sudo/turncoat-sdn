"""The attack profile interface: an attack, and the moment it turns.

A turncoat behaves honestly until its onset, ``start_s``, and only then turns
hostile. The final-year project's node agent did this by "arming" its
``--malicious`` mode after a delay; before that it served every task and
reported its load truthfully. :class:`ServerAttack` keeps that rule in one
place, so an attack only has to say what it does once it has turned.

A server attack can change two things the simulator asks of every node:

* how it **serves** a task it has accepted (:meth:`ServerAttack.serve`), and
* what it **reports** when the controller polls it
  (:meth:`ServerAttack.report`).

Subclass it, give it a ``name`` (the ground-truth label written into the
recording's ``topology`` event), and override either method. The simulator
calls :meth:`~ServerAttack.service_time` and :meth:`~ServerAttack.status`,
which apply the onset and then call yours.

An attack must draw any randomness from the ``rng`` it is handed. The
simulator gives every attacker its own seeded stream, so a random attack stays
reproducible and never shifts the workload other strategies are paired on.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar, NamedTuple


class Status(NamedTuple):
    """What a server reports, and how fast it answers, at one controller poll."""

    claimed_cpu: float
    """The load the server claims, 0 to 1."""
    rtt_ms: float
    """How long the controller waited for the answer, in milliseconds."""


class ServerAttack:
    """An edge server that turns hostile at ``start_s``.

    Override :meth:`serve`, :meth:`report` or both. Before the onset neither is
    called and the server is honest. One instance can be shared by many runs:
    keep per-run state out of it, and derive anything time-dependent from the
    ``now`` each call receives.

    Attributes:
        name: Ground-truth label written to the ``topology`` event, and the
            label the attack scorer checks its verdict against.
        start_s: Simulated second at which the attack begins.
    """

    name: ClassVar[str] = ""

    def __init__(self, start_s: float = 0.0) -> None:
        if not self.name:
            raise TypeError(f"{type(self).__name__} must set a class-level `name`")
        if not (isinstance(start_s, (int, float)) and math.isfinite(start_s) and start_s >= 0):
            raise ValueError(f"start_s must be a finite number of seconds >= 0, got {start_s!r}")
        self.start_s = float(start_s)

    def active(self, now: float) -> bool:
        """Whether the attack has begun by simulated time ``now``."""
        return now >= self.start_s

    # --- Called by the simulator. These apply the onset; don't override. ---

    def service_time(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        """Seconds a task accepted at ``now`` holds a worker, or ``None`` to drop it."""
        if not self.active(now):
            return demand_s
        return self.serve(now, demand_s, rng)

    def status(self, now: float, honest: Status, jitter_ms: float, rng: random.Random) -> Status:
        """What the server reports at the poll at ``now``."""
        if not self.active(now):
            return honest
        return self.report(now, honest, jitter_ms, rng)

    # --- Override these to define the attack. -------------------------------

    def serve(self, now: float, demand_s: float, rng: random.Random) -> float | None:
        """Serve a task after the onset.

        Args:
            now: Simulated time the task starts to occupy a worker.
            demand_s: The task's honest service time, drawn by the simulator.
            rng: This attacker's own seeded random stream.

        Returns:
            Seconds the task holds a worker before it completes, or ``None`` to
            accept it and never answer: the worker is held and the client times
            out. The default serves honestly.
        """
        return demand_s

    def report(self, now: float, honest: Status, jitter_ms: float, rng: random.Random) -> Status:
        """Answer a controller poll after the onset.

        Args:
            now: Simulated time of the poll.
            honest: What an honest server in this one's position would report:
                its true load, and the healthy round-trip plus this poll's
                jitter.
            jitter_ms: This poll's network jitter, already included in
                ``honest.rtt_ms``, for an attack that sets its own RTT.
            rng: This attacker's own seeded random stream.

        Returns:
            The status the controller sees. The default reports honestly.
        """
        return honest

    def ground_truth(self) -> dict[str, float | str]:
        """The ``attack`` and ``attack_start_s`` fields for this server's topology node."""
        return {"attack": self.name, "attack_start_s": self.start_s}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(start_s={self.start_s:g})"
