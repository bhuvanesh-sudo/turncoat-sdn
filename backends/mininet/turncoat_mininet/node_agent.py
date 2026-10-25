"""The HTTP agent on one edge server: serves tasks, answers ``/status`` polls.

Ported from the final-year project's ``simulation/node_agent.py``. The project
gave the agent its own ``--malicious`` branches and its own arming timer. Here
the agent holds a :class:`turncoat_sdn.attacks.ServerAttack`, built exactly as
the simulator builds that attack, and asks it the same two questions the
simulator does:

* ``attack.service_time(now, demand_s, rng)``: how long a task holds a worker,
  or ``None`` to accept it and never answer (blackhole, grayhole);
* ``attack.status(now, honest, 0.0, rng)``: what to claim at a poll, and how
  slowly to answer it (Sybil, on-off).

The onset (``start_s``) is applied by the attack itself, so a turncoat is
honest until then, in a live run as in a simulated one. ``now`` is seconds
since the run's shared start time ``--t0``, so the agent and the controller
agree on when an attack turned.

Endpoints:
    POST /task    body {"task": int, "demand_s": float}; replies
                  {"ok": true, "node_id": ...} after the work, or never.
    GET  /status  {"node_id", "cpu_load", "active_tasks", "queued", "concurrency"}

Runs inside a Mininet host's namespace, so it needs only the standard library
and the core package. It never imports Mininet or os-ken.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from turncoat_sdn.attacks import ServerAttack, Status
from turncoat_sdn.sim import SimConfig, scenario_attacks
from turncoat_sdn.sim.config import ATTACK_SEED_OFFSET

logger = logging.getLogger("turncoat_mininet.node_agent")

#: How the agent spends a task's service time. ``sleep`` holds a worker without
#: using CPU, so every agent on one machine gets the service times the
#: simulator draws. ``burn`` hashes for that long, as the project's agent did,
#: so a slowed Sybil really loads the box; on a small machine every agent then
#: competes for the same cores and service times stretch.
WORK_MODES = ("sleep", "burn")

#: Attack name -> the simulator scenario that builds it, as ``turncoat run
#: --attack`` names them (a test keeps the two in step). Not imported from
#: ``turncoat_sdn.cli``, which pulls in SciPy and would cost every agent seconds
#: of start-up.
ATTACKS: dict[str, str] = {
    "sybil": "sybil",
    "blackhole": "drop",
    "drop": "drop",
    "grayhole": "grayhole",
    "onoff": "onoff",
}


def build_attack(
    name: str, start_s: float = 0.0, config: SimConfig | None = None
) -> ServerAttack | None:
    """The attack a node runs, configured as the simulator's scenario builds it.

    ``name`` is ``none`` or one of the ``--attack`` names of ``turncoat run``
    (``sybil``, ``blackhole``, ``drop``, ``grayhole``, ``onoff``). Settings
    such as the Sybil's claimed load come from ``config``, so a live attacker
    behaves like the simulated one with the same :class:`SimConfig`.
    """
    if name == "none":
        return None
    if name not in ATTACKS:
        raise ValueError(f"unknown attack {name!r}; expected none or one of {list(ATTACKS)}")
    cfg = replace(config or SimConfig(), n_nodes=1, attack_start_s=start_s)
    (attack,) = scenario_attacks(ATTACKS[name], cfg).values()
    return attack


def _burn(seconds: float) -> None:
    end = time.perf_counter() + seconds
    buf = b"turncoat-sdn-workload"
    while time.perf_counter() < end:
        buf = hashlib.sha256(buf).digest()


class NodeAgent:
    """One server's state: its workers, its attack and its clock.

    Args:
        node_id: ``srv1`` to ``srvN``.
        attack: What it does once it turns, or ``None`` for an honest node.
        t0: Wall-clock time (``time.time()``) the run started. Attack onsets
            are measured from here.
        seed: Seeds the attack's random stream, as the simulator does.
        config: Concurrency, the healthy poll RTT and the client timeout.
        work: ``sleep`` or ``burn``, see :data:`WORK_MODES`.
        clock: Wall-clock source, for tests.
    """

    def __init__(
        self,
        node_id: str,
        attack: ServerAttack | None = None,
        *,
        t0: float | None = None,
        seed: int = 1,
        config: SimConfig | None = None,
        work: str = "sleep",
        clock: Any = time.time,
    ) -> None:
        if work not in WORK_MODES:
            raise ValueError(f"work must be one of {WORK_MODES}, got {work!r}")
        self.node_id = node_id
        self.attack = attack
        self.config = config or SimConfig()
        self.work = work
        self.clock = clock
        self.t0 = clock() if t0 is None else t0
        index = int(node_id[3:]) - 1 if node_id[3:].isdigit() else 0
        self._rng = random.Random(seed + ATTACK_SEED_OFFSET + index)
        self._rng_lock = threading.Lock()
        self._workers = threading.BoundedSemaphore(self.config.concurrency)
        self._lock = threading.Lock()
        self.busy = 0
        self.queued = 0
        self.served = 0
        self.dropped = 0

    def now(self) -> float:
        """Seconds since the run started."""
        return self.clock() - self.t0

    def run_task(self, demand_s: float) -> bool:
        """Serve one task. Returns ``False`` if the attack dropped it."""
        with self._lock:
            self.queued += 1
        self._workers.acquire()
        with self._lock:
            self.queued -= 1
            self.busy += 1
        try:
            if self.attack is None:
                service: float | None = demand_s
            else:
                with self._rng_lock:
                    service = self.attack.service_time(self.now(), demand_s, self._rng)
            if service is None:
                # Accept and never answer: hold the worker until the client has
                # given up, exactly as the simulator holds it.
                time.sleep(self.config.task_timeout_s)
                with self._lock:
                    self.dropped += 1
                return False
            if self.work == "burn":
                _burn(service)
            else:
                time.sleep(service)
            with self._lock:
                self.served += 1
            return True
        finally:
            with self._lock:
                self.busy -= 1
            self._workers.release()

    def status(self) -> tuple[dict[str, Any], float]:
        """The ``/status`` reply, and how many seconds to hold it before answering."""
        with self._lock:
            busy, queued = self.busy, self.queued
        concurrency = self.config.concurrency
        honest = Status(min(1.0, (busy + queued) / concurrency), self.config.base_rtt_ms)
        reported = honest
        if self.attack is not None:
            with self._rng_lock:
                reported = self.attack.status(self.now(), honest, 0.0, self._rng)
        # The attack's RTT is relative to a healthy answer; the network supplies
        # the healthy part, the agent only adds the attacker's extra delay.
        delay_s = max(0.0, reported.rtt_ms - honest.rtt_ms) / 1000.0
        body = {
            "node_id": self.node_id,
            "cpu_load": round(reported.claimed_cpu, 4),
            "active_tasks": busy,
            "queued": queued,
            "concurrency": concurrency,
        }
        return body, delay_s


def make_handler(agent: NodeAgent) -> type[BaseHTTPRequestHandler]:
    """A request handler class bound to ``agent``."""

    class AgentHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("%s - %s", self.address_string(), fmt % args)

        def _reply(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/status":
                self._reply(404, {"error": "not found"})
                return
            body, delay_s = agent.status()
            if delay_s:
                time.sleep(delay_s)
            self._reply(200, body)

        def do_POST(self) -> None:
            if self.path != "/task":
                self._reply(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                task = json.loads(self.rfile.read(length) or b"{}")
                demand_s = float(task.get("demand_s", agent.config.service_mean_s))
            except (ValueError, TypeError, AttributeError):
                self._reply(400, {"error": "body must be JSON with a numeric demand_s"})
                return
            if not 0 <= demand_s < 3600:
                self._reply(400, {"error": "demand_s must be between 0 and 3600"})
                return
            if agent.run_task(demand_s):
                self._reply(200, {"ok": True, "node_id": agent.node_id})
            # A dropped task gets no reply at all: the connection just closes.

    return AgentHandler


def serve(agent: NodeAgent, host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer:
    """Bind the agent's HTTP server. Call ``serve_forever()`` on the result."""
    server = ThreadingHTTPServer((host, port), make_handler(agent))
    server.daemon_threads = True
    return server


def build_parser() -> argparse.ArgumentParser:
    """The agent's command line, apart from :func:`main` so launch commands can be checked."""
    parser = argparse.ArgumentParser(
        prog="python -m turncoat_mininet.node_agent",
        description="turncoat-sdn edge-server agent for the live testbed",
    )
    parser.add_argument("--node-id", required=True, help="srv1 to srvN")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--attack",
        choices=["none", *ATTACKS],
        default="none",
        help="what this node does once it turns (default none)",
    )
    parser.add_argument(
        "--start-s",
        type=float,
        default=0.0,
        help="seconds after --t0 at which the attack turns (default 0)",
    )
    parser.add_argument(
        "--t0", type=float, default=None, help="run start, as time.time() (default: now)"
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=SimConfig.concurrency)
    parser.add_argument("--task-timeout-s", type=float, default=SimConfig.task_timeout_s)
    parser.add_argument("--work", choices=WORK_MODES, default="sleep")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    config = replace(SimConfig(), concurrency=args.concurrency, task_timeout_s=args.task_timeout_s)
    attack = build_attack(args.attack, args.start_s, config)
    agent = NodeAgent(
        args.node_id, attack, t0=args.t0, seed=args.seed, config=config, work=args.work
    )
    server = serve(agent, args.host, args.port)
    logger.info("%s listening on %s:%d, attack %r", args.node_id, args.host, args.port, attack)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
