"""One IoT device: sends tasks through the live controller and reports outcomes.

A slimmed port of the final-year project's ``simulation/iot_client.py``. Each
task is three requests:

1. ``POST /route`` to the controller, which names a server (or refuses);
2. ``POST /task`` straight to that server's agent, across the emulated
   network, waiting at most the client timeout;
3. ``POST /report`` back to the controller: ``success``, ``timeout`` or
   ``failure`` (the connection failed outright), with the latency.

Arrivals are Poisson and open-loop, as in the simulator: a device does not
wait for one task to finish before sending the next, so a slow server builds
a real backlog. The project's authentication handshake, flood and spoof modes
are not ported yet; the live run covers the server attacks.

Stdlib and the core package only. Runs inside a Mininet host's namespace, or
on loopback for the no-Mininet run.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from turncoat_sdn.sim import SimConfig

logger = logging.getLogger("turncoat_mininet.iot_client")

#: How long a ``/route`` or ``/report`` call to the controller may take.
CONTROLLER_TIMEOUT_S = 2.0


def _post(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, json.loads(reply.read() or b"{}")
    except urllib.error.HTTPError as exc:
        with exc:
            try:
                body = json.loads(exc.read() or b"{}")
            except ValueError:
                body = {}
        return exc.code, body


def send_task(url: str, task: int, demand_s: float, timeout_s: float) -> tuple[str, float]:
    """Send one task to an agent. Returns its status and the latency in ms."""
    start = time.perf_counter()
    try:
        code, body = _post(f"{url}/task", {"task": task, "demand_s": demand_s}, timeout_s)
        status = "success" if code == 200 and body.get("ok") else "failure"
    except TimeoutError:
        status = "timeout"
    except urllib.error.URLError as exc:
        status = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "failure"
    except (OSError, ValueError):
        # A dropped task closes the connection without a reply. The client
        # has spent the whole wait on it, so it counts as a timeout.
        status = "timeout" if time.perf_counter() - start >= timeout_s * 0.95 else "failure"
    latency_ms = (time.perf_counter() - start) * 1000.0
    if status == "timeout":
        latency_ms = max(latency_ms, timeout_s * 1000.0)
    return status, latency_ms


class IotClient:
    """Sends Poisson task arrivals through the controller.

    Args:
        device_id: ``iot1`` to ``iotN``.
        controller: Base URL of the controller API, e.g. ``http://10.0.99.254:8081``.
        rate_hz: Mean tasks per second this device sends.
        duration_s: How long to send, from ``t0``.
        t0: Wall-clock start of the run (``time.time()``). The client waits
            for it before its first task.
        seed: Seeds this device's arrival times.
        timeout_s: How long to wait for a task before giving up.
    """

    def __init__(
        self,
        device_id: str,
        controller: str,
        *,
        rate_hz: float,
        duration_s: float,
        t0: float | None = None,
        seed: int = 1,
        timeout_s: float = SimConfig.task_timeout_s,
        sender: Callable[[str, int, float, float], tuple[str, float]] = send_task,
    ) -> None:
        if rate_hz <= 0:
            raise ValueError(f"rate_hz must be positive, got {rate_hz}")
        self.device_id = device_id
        self.controller = controller.rstrip("/")
        self.rate_hz = rate_hz
        self.duration_s = duration_s
        self.t0 = time.time() if t0 is None else t0
        index = int(device_id[3:]) if device_id[3:].isdigit() else 0
        self._rng = random.Random(seed * 1_000_003 + index)
        self.timeout_s = timeout_s
        self._send = sender
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.counts = {"sent": 0, "denied": 0, "success": 0, "timeout": 0, "failure": 0}

    def stop(self) -> None:
        self._stop.set()

    def _one(self) -> None:
        try:
            code, answer = _post(
                f"{self.controller}/route", {"device": self.device_id}, CONTROLLER_TIMEOUT_S
            )
        except (OSError, ValueError) as exc:
            logger.warning("%s: controller unreachable for /route: %s", self.device_id, exc)
            return
        if code != 200 or "url" not in answer:
            with self._lock:
                self.counts["denied"] += 1
            return
        status, latency_ms = self._send(
            answer["url"], int(answer["task"]), float(answer["demand_s"]), self.timeout_s
        )
        with self._lock:
            self.counts[status] += 1
        try:
            _post(
                f"{self.controller}/report",
                {
                    "task": answer["task"],
                    "status": status,
                    "latency_ms": latency_ms,
                    "device": self.device_id,
                },
                CONTROLLER_TIMEOUT_S,
            )
        except (OSError, ValueError) as exc:
            logger.warning("%s: report for task %s lost: %s", self.device_id, answer["task"], exc)

    def hello(self) -> bool:
        """Tell the controller this device is up. Retries until ``t0``."""
        while True:
            try:
                code, _ = _post(
                    f"{self.controller}/hello", {"device": self.device_id}, CONTROLLER_TIMEOUT_S
                )
                if code == 200:
                    return True
            except (OSError, ValueError):
                pass
            if time.time() >= self.t0 or self._stop.wait(0.2):
                return False

    def run(self) -> dict[str, int]:
        """Say hello, then send tasks until ``duration_s`` after ``t0``. Returns the counts."""
        if not self.hello():
            logger.warning("%s: the controller never answered /hello", self.device_id)
        if self._stop.wait(max(0.0, self.t0 - time.time())):
            return dict(self.counts)
        end = self.t0 + self.duration_s
        next_at = time.time() + self._rng.expovariate(self.rate_hz)
        while next_at < end:
            if self._stop.wait(max(0.0, next_at - time.time())):
                break
            with self._lock:
                self.counts["sent"] += 1
            threading.Thread(target=self._one, daemon=True).start()
            next_at += self._rng.expovariate(self.rate_hz)
        # Let tasks still in flight finish and report.
        self._stop.wait(self.timeout_s + CONTROLLER_TIMEOUT_S)
        return dict(self.counts)


def build_parser() -> argparse.ArgumentParser:
    """The client's command line, apart from :func:`main` so launch commands can be checked."""
    parser = argparse.ArgumentParser(
        prog="python -m turncoat_mininet.iot_client",
        description="turncoat-sdn IoT client for the live testbed",
    )
    parser.add_argument("--device-id", required=True, help="iot1 to iotN")
    parser.add_argument("--controller", required=True, help="controller API base URL")
    parser.add_argument("--rate-hz", type=float, required=True, help="mean tasks per second")
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--t0", type=float, default=None, help="run start, as time.time()")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=SimConfig.task_timeout_s)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    client = IotClient(
        args.device_id,
        args.controller,
        rate_hz=args.rate_hz,
        duration_s=args.duration_s,
        t0=args.t0,
        seed=args.seed,
        timeout_s=args.timeout_s,
    )
    counts = client.run()
    logger.info("%s done: %s", args.device_id, counts)


if __name__ == "__main__":
    main()
