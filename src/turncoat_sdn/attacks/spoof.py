"""Identity spoof: an IoT device that claims to be another device.

Ported from the final-year project's ``--malicious spoof`` IoT client
(``simulation/iot_client.py``), where iot38 authenticated as iot1 fifteen
seconds into the run. The project's PRESENT-80 key was fleet-wide, so the
spoofer's cryptographic response was always correct: holding the key proves
membership of the fleet, not ownership of an identity. What stops it is the
controller binding each device id to a source address. A request for iot1
that arrives from iot38's address is refused, however good its crypto.

So the attack models a device that holds the fleet key and a target to
impersonate. From its onset it sends a request claiming the target's identity
every ``interval_s`` seconds, from its own address. If the controller refuses
it, it tries again at the next interval; if it is admitted, it goes on sending
work as the target. Its ordinary traffic as itself carries on throughout.

It draws no random numbers: the requests fall on a fixed beat from the onset,
so the same run is the same however the strategies route.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import random

from turncoat_sdn.attacks.client import ClientAttack

#: The final-year project's IoT devices reported every 2 s, and so does the spoofer.
DEFAULT_INTERVAL_S = 2.0


class IdentitySpoof(ClientAttack):
    """Claims another client's identity from its own address, from ``start_s`` on.

    Args:
        start_s: Simulated second of its first request as the target.
        target: Client index of the device it impersonates.
        interval_s: Seconds between its requests as the target.
    """

    name = "spoof"

    def __init__(
        self, start_s: float = 0.0, *, target: int = 0, interval_s: float = DEFAULT_INTERVAL_S
    ) -> None:
        super().__init__(start_s)
        if isinstance(target, bool) or not isinstance(target, int) or target < 0:
            raise ValueError(f"target must be a client index >= 0, got {target!r}")
        if not (
            isinstance(interval_s, (int, float)) and math.isfinite(interval_s) and interval_s > 0
        ):
            raise ValueError(f"interval_s must be finite seconds > 0, got {interval_s!r}")
        self.target = target
        self.interval_s = float(interval_s)

    def interval(self, now: float, rng: random.Random) -> float | None:
        return self.interval_s

    def claim(self, own: int, now: float) -> int:
        return self.target

    def __repr__(self) -> str:
        return (
            f"IdentitySpoof(start_s={self.start_s:g}, target={self.target}, "
            f"interval_s={self.interval_s:g})"
        )
