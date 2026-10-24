"""The client attack interface: an IoT device that turns at ``start_s``.

:class:`~turncoat_sdn.attacks.ServerAttack` changes how a server serves and
reports. A client attack is the other side of the network: one of the IoT
devices that sends the work. It keeps sending its ordinary traffic as itself,
which the simulator draws from the shared arrival stream, and from its onset
it also sends requests of its own, which the attack decides.

A client attack can change two things about each request it sends:

* **when** it sends the next one (:meth:`ClientAttack.interval`), and
* **which identity** the request claims (:meth:`ClientAttack.claim`).

The request always leaves from the attacker's own address. The controller's
admission check sees that address and the claimed identity, and either admits
the request into routing or refuses it. Whether it is refused is the
controller's decision, never the attack's.

Subclass it, give it a ``name`` (the ground-truth label written into the
recording's ``topology`` event), and override :meth:`~ClientAttack.interval`,
:meth:`~ClientAttack.claim` or both. The simulator calls
:meth:`~ClientAttack.first_request_s`, :meth:`~ClientAttack.next_request_s`
and :meth:`~ClientAttack.identity`, which apply the onset and then call yours.

Clients are numbered by index, as servers are: client ``j`` is ``iot<j+1>``
in a recording. The same rules as for a server attack apply: draw randomness
only from the ``rng`` you are handed, and keep no per-run state on the
instance.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar


class ClientAttack:
    """An IoT client that turns hostile at ``start_s``.

    Its own requests start at the onset. Before it, the client sends only its
    ordinary traffic, as itself, and is indistinguishable from an honest one.

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

    def first_request_s(self) -> float:
        """Simulated time of the attacker's first request of its own: its onset."""
        return self.start_s

    def next_request_s(self, now: float, rng: random.Random) -> float | None:
        """Time of the request after the one sent at ``now``, or ``None`` to stop."""
        gap = self.interval(now, rng)
        if gap is None:
            return None
        if not (math.isfinite(gap) and gap > 0):
            raise ValueError(f"{type(self).__name__}.interval must return seconds > 0, got {gap!r}")
        return now + gap

    def identity(self, own: int, now: float) -> int:
        """The client index the request sent at ``now`` claims to come from."""
        if not self.active(now):
            return own
        return self.claim(own, now)

    # --- Override these to define the attack. -------------------------------

    def interval(self, now: float, rng: random.Random) -> float | None:
        """Seconds from the request sent at ``now`` to the next one.

        Args:
            now: Simulated time of the request just sent.
            rng: This attacker's own seeded random stream.

        Returns:
            A gap in seconds, or ``None`` to send nothing more. The default
            sends one request at the onset and stops.
        """
        return None

    def claim(self, own: int, now: float) -> int:
        """The client index a request after the onset claims to come from.

        Args:
            own: This attacker's own client index.
            now: Simulated time of the request.

        Returns:
            A client index. The default claims its own identity.
        """
        return own

    def ground_truth(self) -> dict[str, float | str]:
        """The ``attack`` and ``attack_start_s`` fields for this client's topology node."""
        return {"attack": self.name, "attack_start_s": self.start_s}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(start_s={self.start_s:g})"
