"""The live network: a seeded plan, the Mininet build, and the launch commands.

Ported from the final-year project's ``simulation/topology.py``. The shape is
unchanged, three tiers:

    s0 (core) --5ms, 1 Gbit/s-- s1..sN (edge) --2ms, 100 Mbit/s-- srv1..srvN
                                s1..sN        --1-10ms, 10 Mbit/s-- iot1..iotM

with IoT devices attached round-robin to the edge switches, every switch on an
explicit nonzero DPID, and a ``cx`` node in the root namespace so the
controller can reach the emulated subnets.

Three changes from the original:

* **The plan is pure and seeded.** :func:`plan_topology` decides every host,
  address and link without Mininet. The per-IoT link delay was drawn from an
  unseeded ``random.randint(1, 10)``, so no two runs had the same network; it
  is now drawn from the run's seed, and the plan goes into the recording.
* **No OpenFlow controller is needed.** The switches run Open vSwitch's
  ``standalone`` fail mode, a plain learning switch, because routing decisions
  are made by :mod:`turncoat_mininet.controller` at the application layer.
  Pass an OpenFlow controller address to use one anyway.
* **Launch commands are data.** :func:`agent_command` and
  :func:`client_command` return argument lists, so a test can check every
  command parses before anything runs (the project's live-config preflight).

Mininet is imported only inside :func:`build_network`; everything else here
runs on any machine.
"""

from __future__ import annotations

import logging
import random
import shlex
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from turncoat_mininet.addressing import (
    AGENT_PORT,
    CX_IP,
    CX_PREFIX,
    iot_ip,
    iot_mac,
    srv_ip,
    srv_mac,
)
from turncoat_sdn.attacks import ServerAttack
from turncoat_sdn.sim import SimConfig

logger = logging.getLogger("turncoat_mininet.topology")

#: Seed offset for the IoT link delays, clear of the simulator's streams.
LINK_SEED_OFFSET = 401

#: The directory that holds the ``turncoat_mininet`` package, put on
#: ``PYTHONPATH`` for every launched process so the backend runs from a clone
#: without being installed.
BACKEND_ROOT = Path(__file__).resolve().parent.parent

CX_NAME = "cx"


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    delay_ms: int
    bw_mbps: int

    def as_event(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "delay_ms": self.delay_ms, "bw_mbps": self.bw_mbps}


@dataclass(frozen=True)
class Plan:
    """Every host, switch and link of one run's network."""

    n_servers: int
    n_clients: int
    switches: tuple[str, ...]
    servers: tuple[str, ...]
    clients: tuple[str, ...]
    links: tuple[Link, ...]
    client_switch: Mapping[str, str] = field(default_factory=dict)

    def switch_nodes(self) -> list[dict[str, str]]:
        """Switches as ``topology`` nodes: they carry no ground truth."""
        return [
            {"id": s, "kind": "core_switch" if s == "s0" else "edge_switch"} for s in self.switches
        ]


def plan_topology(n_servers: int, n_clients: int, seed: int = 1) -> Plan:
    """Lay out the three-tier network. The same arguments give the same plan."""
    if not 1 <= n_servers <= 250:
        raise ValueError(f"n_servers must be 1 to 250, got {n_servers}")
    if not 1 <= n_clients <= 250:
        raise ValueError(f"n_clients must be 1 to 250, got {n_clients}")
    rng = random.Random(seed + LINK_SEED_OFFSET)
    switches = ["s0"]
    servers: list[str] = []
    links: list[Link] = []
    for i in range(1, n_servers + 1):
        sw, srv = f"s{i}", f"srv{i}"
        switches.append(sw)
        servers.append(srv)
        links.append(Link(sw, srv, 2, 100))
        links.append(Link("s0", sw, 5, 1000))
    clients: list[str] = []
    client_switch: dict[str, str] = {}
    for j in range(1, n_clients + 1):
        dev = f"iot{j}"
        sw = f"s{(j - 1) % n_servers + 1}"
        clients.append(dev)
        client_switch[dev] = sw
        links.append(Link(dev, sw, rng.randint(1, 10), 10))
    return Plan(
        n_servers,
        n_clients,
        tuple(switches),
        tuple(servers),
        tuple(clients),
        tuple(links),
        client_switch,
    )


# --- Launch commands --------------------------------------------------------


def agent_command(
    i: int,
    attack: ServerAttack | None,
    *,
    t0: float,
    seed: int,
    config: SimConfig,
    host: str = "0.0.0.0",
    port: int = AGENT_PORT,
    work: str = "sleep",
    python: str = sys.executable,
) -> list[str]:
    """The command that starts ``srv{i}``'s agent (1-based ``i``)."""
    return [
        python,
        "-m",
        "turncoat_mininet.node_agent",
        "--node-id",
        f"srv{i}",
        "--host",
        host,
        "--port",
        str(port),
        "--attack",
        attack.name if attack is not None else "none",
        "--start-s",
        repr(attack.start_s if attack is not None else 0.0),
        "--t0",
        repr(t0),
        "--seed",
        str(seed),
        "--concurrency",
        str(config.concurrency),
        "--task-timeout-s",
        repr(config.task_timeout_s),
        "--work",
        work,
    ]


def client_command(
    j: int,
    *,
    controller: str,
    rate_hz: float,
    duration_s: float,
    t0: float,
    seed: int,
    config: SimConfig,
    python: str = sys.executable,
) -> list[str]:
    """The command that starts ``iot{j}``'s client (1-based ``j``)."""
    return [
        python,
        "-m",
        "turncoat_mininet.iot_client",
        "--device-id",
        f"iot{j}",
        "--controller",
        controller,
        "--rate-hz",
        repr(rate_hz),
        "--duration-s",
        repr(duration_s),
        "--t0",
        repr(t0),
        "--seed",
        str(seed),
        "--timeout-s",
        repr(config.task_timeout_s),
    ]


def shell_line(argv: Sequence[str], log: str) -> str:
    """``argv`` as a backgrounded shell line for ``host.cmd()``, logging to ``log``."""
    return (
        f"PYTHONPATH={shlex.quote(str(BACKEND_ROOT))}${{PYTHONPATH:+:$PYTHONPATH}} "
        f"{shlex.join(argv)} > {shlex.quote(log)} 2>&1 &"
    )


# --- Mininet ------------------------------------------------------------------


def mininet_available() -> bool:
    try:
        import mininet.net  # noqa: F401
    except ImportError:
        return False
    return True


def build_network(plan: Plan, of_controller: tuple[str, int] | None = None) -> Any:
    """Build (but do not start) the Mininet network for ``plan``.

    Without ``of_controller`` the switches run in OVS ``standalone`` mode and
    learn MAC addresses on their own. With ``(ip, port)`` they connect to that
    OpenFlow 1.3 controller instead, for example an os-ken learning switch.
    """
    from mininet.link import TCLink
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo

    fail_mode = "secure" if of_controller else "standalone"

    class TurncoatTopo(Topo):
        def build(self) -> None:
            for k, name in enumerate(plan.switches):
                # dpid 0 is rejected by some OVS versions; start at 1.
                self.addSwitch(
                    name,
                    cls=OVSSwitch,
                    protocols="OpenFlow13",
                    dpid=f"{k + 1:016x}",
                    failMode=fail_mode,
                )
            for i in range(1, plan.n_servers + 1):
                self.addHost(f"srv{i}", ip=f"{srv_ip(i)}/8", mac=srv_mac(i))
            for j in range(1, plan.n_clients + 1):
                self.addHost(f"iot{j}", ip=f"{iot_ip(j)}/8", mac=iot_mac(j))
            for link in plan.links:
                self.addLink(
                    link.a, link.b, cls=TCLink, delay=f"{link.delay_ms}ms", bw=link.bw_mbps
                )

    if of_controller:
        ip, port = of_controller
        return Mininet(
            topo=TurncoatTopo(),
            controller=lambda name: RemoteController(name, ip=ip, port=port),
            switch=OVSSwitch,
            link=TCLink,
        )
    return Mininet(topo=TurncoatTopo(), controller=None, switch=OVSSwitch, link=TCLink)


def add_cx_node(net: Any) -> Any:
    """Add the root-namespace ``cx`` node on the core switch. Call after ``net.start()``.

    The controller runs outside every Mininet namespace and reaches the
    emulated hosts through this hop; the hosts reach the controller's API at
    :data:`~turncoat_mininet.addressing.CX_IP`.
    """
    from mininet.link import TCLink
    from mininet.node import Node

    core = net.get("s0")
    cx = net.addHost(CX_NAME, cls=Node, ip=None, inNamespace=False)
    link = net.addLink(cx, core, cls=TCLink, bw=1000)
    # addLink() after start() makes the veth pair but does not add the switch
    # end to the OVS bridge; without this attach every poll times out while
    # the interface looks healthy.
    core.attach(link.intf2)
    intf = cx.intfNames()[-1]
    cx.cmd(f"ip link set {intf} up")
    cx.cmd(f"ip addr add {CX_IP}/{CX_PREFIX} dev {intf}")
    cx.cmd(f"ip route add 10.0.0.0/24 dev {intf}")
    cx.cmd(f"ip route add 10.0.1.0/24 dev {intf}")
    logger.info("cx up: %s/%d on %s", CX_IP, CX_PREFIX, intf)
    return cx


def reachability_pairs(plan: Plan) -> list[tuple[str, str]]:
    """Which host pairs the reachability check pings: linear, not quadratic.

    Every client pings one server, round-robin, and every server pings one
    client back, since paths are per-direction. ``pingAll`` at 8 servers and
    40 clients is 2,352 pings and took 163 s in the project's run 1; this is 48.
    """
    pairs = [(c, plan.servers[k % len(plan.servers)]) for k, c in enumerate(plan.clients)]
    pairs += [(s, plan.clients[k % len(plan.clients)]) for k, s in enumerate(plan.servers)]
    return pairs


def check_reachability(net: Any, plan: Plan) -> float:
    """Ping the sampled pairs once each; return the loss in percent."""
    pairs = reachability_pairs(plan)
    started = time.time()
    lost = 0
    for src, dst in pairs:
        out = net.get(src).cmd(f"ping -c1 -W1 {net.get(dst).IP()}")
        if " 0% packet loss" not in out:
            lost += 1
            logger.warning("reachability: %s -> %s did not answer", src, dst)
    loss = 100.0 * lost / len(pairs)
    logger.info(
        "reachability: %.1f%% loss over %d pairs in %.1fs", loss, len(pairs), time.time() - started
    )
    return loss


def stop_processes(net: Any, plan: Plan) -> None:
    """Kill every agent and client before ``net.stop()``."""
    for srv in plan.servers:
        net.get(srv).cmd("pkill -f turncoat_mininet.node_agent 2>/dev/null")
    for dev in plan.clients:
        net.get(dev).cmd("pkill -f turncoat_mininet.iot_client 2>/dev/null")
