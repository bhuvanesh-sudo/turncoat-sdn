"""The live controller: routes real tasks, polls real agents, records ``events.jsonl``.

It makes the controller decisions the simulator makes, with the same code,
on a real network instead of a simulated one:

* **routing** with a strategy from :data:`turncoat_sdn.cli.routers.STRATEGIES`;
* **trust** from :class:`turncoat_sdn.trust.SimTrustModel`, one update per
  task outcome a client reports;
* **detection** with :func:`turncoat_sdn.sim.detect_anomalies` (the latency
  tell and the timeout-rate tell) once per poll of every agent's ``/status``;
* **recording** with :class:`turncoat_sdn.events.EventWriter`, in schema 1.0,
  with ``backend="live"``.

So a live recording carries the same events as a simulated one, and
``turncoat validate`` and ``turncoat score`` read it unchanged.

The final-year project made these decisions inside an os-ken app and steered
traffic with OpenFlow rules on a virtual IP. Here they are made at the
application layer: an IoT client asks ``POST /route`` which server to use, sends
the task straight to that server across the emulated network, and reports the
outcome on ``POST /report``. The switches only forward packets, so no
OpenFlow controller is needed (see the backend README).

This module never imports Mininet or os-ken; the loopback run and the tests
drive it on a plain machine.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from turncoat_sdn.attacks import ServerAttack
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter
from turncoat_sdn.sim import (
    Outcome,
    SimConfig,
    detect_anomalies,
    is_excluded,
    node_id,
)
from turncoat_sdn.sim.config import SELECTION_SEED_OFFSET, SERVICE_SEED_OFFSET
from turncoat_sdn.sim.engine import DENIED_REASON
from turncoat_sdn.trust import SimTrustModel, latency_tell

logger = logging.getLogger("turncoat_mininet.controller")

#: How long a ``/status`` poll may take before the node counts as unanswered.
#: Longer than the Sybil's slow answer (220 ms), shorter than one poll period.
POLL_TIMEOUT_S = 0.8


@dataclass(frozen=True)
class Server:
    """A server the controller routes to and polls."""

    id: str
    """``srv1`` to ``srvN``, in index order."""
    url: str
    """Base URL of its agent, for example ``http://10.0.1.3:8000``."""


@dataclass(frozen=True)
class Device:
    """An IoT client, listed in the recording's topology."""

    id: str
    ip: str | None = None


@dataclass
class Totals:
    """What the run did, counted as the controller saw it."""

    offered: int = 0
    denied: int = 0
    completed: int = 0
    timed_out: int = 0
    failed: int = 0
    polls: int = 0
    quarantines: int = 0
    served: dict[str, int] = field(default_factory=dict)


def topology_graph(
    servers: Sequence[Server],
    attacks: Mapping[int, ServerAttack],
    devices: Sequence[Device] = (),
    links: Sequence[Mapping[str, Any]] = (),
    switches: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """The ``topology`` event's graph: the roster and every attacker's ground truth."""
    nodes: list[dict[str, Any]] = []
    for i, server in enumerate(servers):
        node: dict[str, Any] = {"id": server.id, "kind": "server", "attack": "none"}
        if i in attacks:
            node.update(attacks[i].ground_truth())
        nodes.append(node)
    for device in devices:
        entry: dict[str, Any] = {"id": device.id, "kind": "iot", "attack": "none"}
        if device.ip is not None:
            entry["ip"] = device.ip
        nodes.append(entry)
    nodes.extend(dict(s) for s in switches)
    return {"nodes": nodes, "links": [dict(link) for link in links]}


class LiveController:
    """Routing, trust, detection and recording for one live run.

    Args:
        servers: The fleet, in index order (``servers[0]`` is ``srv1``).
        recorder: An open :class:`~turncoat_sdn.events.EventWriter`.
        strategy: A key of :data:`~turncoat_sdn.cli.routers.STRATEGIES`.
        seed: Seeds routing and the task demands, from the same offsets as the
            simulator.
        config: Concurrency, timeouts, poll period and the detection settings.
        attacks: Ground truth for the topology event, by server index.
        devices: IoT clients to list in the topology.
        links, switches: Extra topology entries (a Mininet run lists its
            switches and links; the loopback run has none).
        clock: Seconds since the run started. Defaults to a monotonic clock
            started by :meth:`start`.
        fetch_status: Polls one server, returning its ``/status`` JSON or
            ``None``. Defaults to an HTTP GET; tests pass a stand-in.
    """

    def __init__(
        self,
        servers: Sequence[Server],
        recorder: EventWriter,
        *,
        strategy: str = "zt_sdn",
        seed: int = 1,
        config: SimConfig | None = None,
        attacks: Mapping[int, ServerAttack] | None = None,
        devices: Sequence[Device] = (),
        links: Sequence[Mapping[str, Any]] = (),
        switches: Sequence[Mapping[str, str]] = (),
        clock: Callable[[], float] | None = None,
        fetch_status: Callable[[Server], dict[str, Any] | None] | None = None,
    ) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}; expected one of {sorted(STRATEGIES)}")
        self.servers = list(servers)
        self.cfg = config or SimConfig()
        n = len(self.servers)
        if self.cfg.n_nodes != n:
            self.cfg = replace(self.cfg, n_nodes=n)
        for i, server in enumerate(self.servers):
            if server.id != node_id(i):
                raise ValueError(f"server {i} must be {node_id(i)}, got {server.id}")
        self.rec = recorder
        self.attacks = dict(attacks or {})
        self._graph = topology_graph(self.servers, self.attacks, devices, links, switches)
        self._started_at: float | None = None
        self._clock = clock
        self._fetch = fetch_status or _http_status

        self._router = STRATEGIES[strategy](n, random.Random(seed + SELECTION_SEED_OFFSET))
        self._svc_rng = random.Random(seed + SERVICE_SEED_OFFSET)
        self._model = SimTrustModel()

        self.trust = [self._model.initial_score] * n
        self.claimed_cpu = [0.0] * n
        self.rtt_ms = [self.cfg.base_rtt_ms] * n
        self.anomaly = [0.0] * n
        self.strikes = [0] * n
        self.recent: list[deque[str]] = [
            deque(maxlen=self.cfg.recent_status_window) for _ in range(n)
        ]
        self.inflight = [0] * n
        self.excluded = [False] * n
        self.totals = Totals(served={s.id: 0 for s in self.servers})
        #: Devices that have said hello, so a run can wait for its clients.
        self.ready: set[str] = set()
        self._routed: dict[int, int] = {}

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=max(1, n), thread_name_prefix="poll")
        self.running = False

    # --- Clock and recording -------------------------------------------------

    def now(self) -> float:
        if self._clock is not None:
            return self._clock()
        assert self._started_at is not None, "start() the controller first"
        return time.perf_counter() - self._started_at

    def _write(self, event_type: str, **fields: Any) -> None:
        # Called with the lock held, so timestamps go out in order.
        self.rec.write(event_type, round(max(0.0, self.now()), 6), **fields)

    # --- Lifecycle -----------------------------------------------------------

    def start(self, poll: bool = True, t0: float | None = None) -> None:
        """Write the topology and begin polling.

        ``ts`` 0 is ``t0``, the run's shared wall-clock start
        (``time.time()``) that every agent measures its attack onset from, or
        this moment if ``t0`` is not given. Anchoring on ``t0`` keeps the
        recording's timestamps and the agents' onsets on one clock even if the
        controller starts a little late.
        """
        with self._lock:
            lag = 0.0 if t0 is None else max(0.0, time.time() - t0)
            self._started_at = time.perf_counter() - lag
            self.rec.write("topology", 0.0, graph=self._graph, config=asdict(self.cfg))
            self.running = True
        if poll:
            self._poller = threading.Thread(target=self._poll_loop, name="poller", daemon=True)
            self._poller.start()

    def stop(self) -> None:
        """Stop polling and stop accepting routes and reports."""
        with self._lock:
            self.running = False
        self._stop.set()
        if self._poller is not None:
            self._poller.join(timeout=5)
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- What the clients call -------------------------------------------------

    def hello(self, device: str) -> None:
        """A client is up and waiting for the start."""
        with self._lock:
            self.ready.add(device)

    def route(self, device: str | None = None, client_ip: str | None = None) -> dict[str, Any]:
        """Choose a server for one new task.

        Returns ``{"task", "node", "url", "demand_s"}``, or ``{"denied": reason}``
        when the strategy refuses (every candidate quarantined) or the run is over.
        """
        with self._lock:
            if not self.running:
                return {"denied": "run over"}
            self.totals.offered += 1
            task = self.totals.offered
            sender = {"client_ip": client_ip} if client_ip else {}
            i = self._router.choose(self.trust, self.claimed_cpu, self.rtt_ms, self.anomaly)
            if i is None:
                self.totals.denied += 1
                self._write("route_denied", reason=DENIED_REASON, task=task, **sender)
                return {"denied": DENIED_REASON}
            demand = self._svc_rng.expovariate(1 / self.cfg.service_mean_s)
            server = self.servers[i]
            self.inflight[i] += 1
            self._routed[task] = i
            self.totals.served[server.id] += 1
            self._write("route", task=task, chosen=server.id, **sender)
            return {"task": task, "node": server.id, "url": server.url, "demand_s": demand}

    def report(self, task: int, status: str, latency_ms: float, device: str | None = None) -> bool:
        """Record one task's outcome and update the server's trust.

        ``status`` is ``success``, ``timeout`` or ``failure`` (the connection
        failed outright). Trust and the timeout-rate tell count a failure as a
        timeout, since the simulator knows only those two. Returns ``False``
        for a task this controller never routed or has already heard about.
        """
        if status not in ("success", "timeout", "failure"):
            raise ValueError(f"status must be success, timeout or failure, got {status!r}")
        with self._lock:
            i = self._routed.pop(task, None)
            if i is None or not self.running:
                return False
            self.inflight[i] -= 1
            if status == "success":
                self.totals.completed += 1
            elif status == "timeout":
                self.totals.timed_out += 1
            else:
                self.totals.failed += 1
            extra = {"device": device} if device else {}
            self._write(
                "report",
                task=task,
                node=self.servers[i].id,
                status=status,
                latency_ms=round(max(0.0, latency_ms), 3),
                **extra,
            )
            outcome = "success" if status == "success" else "timeout"
            self.recent[i].append(outcome)
            self.trust[i] = self._model.update(
                Outcome(
                    node=i,
                    edge_node_id=self.servers[i].id,
                    timestamp=self.now(),
                    task_status=outcome,
                    # The controller's own view of occupancy: tasks it sent
                    # there that have not come back yet.
                    cpu_usage=min(1.0, self.inflight[i] / self.cfg.concurrency),
                    reported_cpu=self.claimed_cpu[i],
                    latency_ms=latency_ms,
                    anomaly_flag=self.anomaly[i] >= self.cfg.anomaly_gate,
                )
            )
            return True

    # --- Polling ---------------------------------------------------------------

    def poll_once(self) -> None:
        """Poll every agent's ``/status`` at once, then run one detection cycle."""
        started = time.perf_counter()
        futures = [self._pool.submit(self._timed_fetch, s) for s in self.servers]
        answers = [f.result() for f in futures]
        with self._lock:
            if not self.running:
                return
            for i, (body, rtt_ms) in enumerate(answers):
                self.rtt_ms[i] = rtt_ms
                if body is not None:
                    try:
                        self.claimed_cpu[i] = min(1.0, max(0.0, float(body["cpu_load"])))
                    except (KeyError, TypeError, ValueError):
                        logger.warning("%s sent a malformed status: %r", self.servers[i].id, body)
            fired = detect_anomalies(
                self.claimed_cpu,
                self.rtt_ms,
                self.recent,
                self.anomaly,
                self.strikes,
                self.cfg,
                latency_tell,
            )
            for i, signals in enumerate(fired):
                if signals:
                    self._write(
                        "anomaly",
                        node=self.servers[i].id,
                        signals=signals,
                        anomaly=round(self.anomaly[i], 6),
                    )
            for i, server in enumerate(self.servers):
                out = is_excluded(self.trust[i], self.anomaly[i], self.cfg)
                if out != self.excluded[i]:
                    self.excluded[i] = out
                    if out:
                        self.totals.quarantines += 1
                    self._write(
                        "quarantine" if out else "recovered",
                        node=server.id,
                        trust=round(self.trust[i], 6),
                        anomaly=round(self.anomaly[i], 6),
                    )
            self.totals.polls += 1
            self._write(
                "node_status",
                nodes={
                    s.id: {
                        "trust": round(self.trust[i], 6),
                        "claimed_cpu": round(self.claimed_cpu[i], 6),
                        "rtt_ms": round(self.rtt_ms[i], 3),
                        "anomaly": round(self.anomaly[i], 6),
                        "inflight": self.inflight[i],
                    }
                    for i, s in enumerate(self.servers)
                },
                poll_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

    def _timed_fetch(self, server: Server) -> tuple[dict[str, Any] | None, float]:
        start = time.perf_counter()
        body = self._fetch(server)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if body is None:
            # Unanswered: as slow as the poll allowed, which is what an
            # unreachable node looks like to the latency tell.
            elapsed_ms = max(elapsed_ms, POLL_TIMEOUT_S * 1000.0)
        return body, elapsed_ms

    def _poll_loop(self) -> None:
        next_at = self.cfg.poll_s
        while not self._stop.wait(max(0.0, next_at - self.now())):
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 -- one bad poll must not end the run
                logger.exception("poll failed")
            next_at += self.cfg.poll_s

    # --- HTTP API ----------------------------------------------------------------

    def serve(self, host: str = "0.0.0.0", port: int = 8081) -> ThreadingHTTPServer:
        """Bind the client API (``/route``, ``/report``, ``/health``)."""
        server = ThreadingHTTPServer((host, port), _make_handler(self))
        server.daemon_threads = True
        server.request_queue_size = 128
        return server


def _http_status(server: Server) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{server.url}/status", timeout=POLL_TIMEOUT_S) as reply:
            return json.loads(reply.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _make_handler(ctrl: LiveController) -> type[BaseHTTPRequestHandler]:
    class ControllerHandler(BaseHTTPRequestHandler):
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

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("body must be a JSON object")
            return data

        def do_GET(self) -> None:
            if self.path == "/health":
                self._reply(200, {"ok": True, "running": ctrl.running})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                body = self._body()
                if self.path == "/hello":
                    ctrl.hello(str(body["device"]))
                    self._reply(200, {"ok": True})
                elif self.path == "/route":
                    answer = ctrl.route(body.get("device"), self.client_address[0])
                    self._reply(503 if "denied" in answer else 200, answer)
                elif self.path == "/report":
                    accepted = ctrl.report(
                        int(body["task"]),
                        str(body["status"]),
                        float(body["latency_ms"]),
                        body.get("device"),
                    )
                    self._reply(200, {"accepted": accepted})
                else:
                    self._reply(404, {"error": "not found"})
            except (KeyError, TypeError, ValueError) as exc:
                self._reply(400, {"error": str(exc)})

    return ControllerHandler
