"""Turncoat attack profiles, one module per attack, each with a ``start_s`` onset.

Owner: ash (Trust model and attacks track); one attack per member in v0.3.
Lands in: v0.3.
Ported from the final-year project:
the attacker branches of evaluation/baseline.py, and the onset ("arming")
logic in simulation/node_agent.py.

Every attack subclasses :class:`ServerAttack`, which keeps the server honest
until ``start_s``. Hand attacks to the simulator by node index::

    from turncoat_sdn.attacks import Blackhole, Sybil
    from turncoat_sdn.sim import simulate

    run = simulate(router, "both", seed=1, attacks={7: Sybil(start_s=30.0), 6: Blackhole()})

or delay a scenario's built-in attackers with ``SimConfig(attack_start_s=...)``.
How to write a new one is in ``docs/attacks.md``.

This package imports nothing else from turncoat_sdn, and must not import
os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.attacks.base import ServerAttack, Status
from turncoat_sdn.attacks.blackhole import Blackhole
from turncoat_sdn.attacks.grayhole import Grayhole
from turncoat_sdn.attacks.on_off import OnOff
from turncoat_sdn.attacks.sybil import Sybil

__all__ = [
    "Blackhole",
    "Grayhole",
    "OnOff",
    "ServerAttack",
    "Status",
    "Sybil",
]
