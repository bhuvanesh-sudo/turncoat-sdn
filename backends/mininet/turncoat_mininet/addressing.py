"""IP and MAC addresses for every host in the live topology, in one place.

Ported from the final-year project's ``simulation/addressing.py``. The topology
builds hosts from these functions and the controller reaches servers by them,
so the two can never disagree about who lives where. IoT addresses match
:func:`turncoat_sdn.sim.client_ip`, so a live recording names devices the same
way a simulated one does.

Stdlib only: no Mininet, so tests and the loopback run import it anywhere.
"""

from __future__ import annotations

import re

#: Address of the ``cx`` node: a plain host in the root namespace, linked to
#: the core switch, through which the controller (which runs outside every
#: Mininet namespace) reaches the emulated subnets. IoT clients reach the
#: controller's API here.
CX_IP = "10.0.99.254"
#: ``cx`` sits on a narrower /24 than the hosts' /8, so its routes stay small.
CX_PREFIX = 24

#: Port every node agent listens on inside its own host.
AGENT_PORT = 8000

_SRV = re.compile(r"srv([1-9][0-9]*)")


def srv_ip(i: int) -> str:
    """Address of server ``srv{i}``, 1-based: ``10.0.1.1`` for ``srv1``."""
    return f"10.0.1.{i}"


def srv_mac(i: int) -> str:
    return f"00:00:00:00:01:{i:02x}"


def iot_ip(j: int) -> str:
    """Address of device ``iot{j}``, 1-based: ``10.0.0.1`` for ``iot1``."""
    return f"10.0.0.{j}"


def iot_mac(j: int) -> str:
    return f"00:00:00:00:00:{j:02x}"


def srv_index(node_id: str) -> int:
    """``"srv3"`` -> 3. Raises ``ValueError`` for anything else."""
    match = _SRV.fullmatch(node_id)
    if match is None:
        raise ValueError(f"not a server node id: {node_id!r}")
    return int(match.group(1))
