"""``python -m turncoat_mininet.run``: one live run, recorded to ``events.jsonl``.

Two networks, one controller:

``--network mininet`` (the default)
    Builds the three-tier topology under Mininet, starts one node agent per
    server and one client per IoT device inside their own hosts, and runs the
    controller in the root namespace behind the ``cx`` node. Needs Linux,
    root, Open vSwitch and Mininet.

``--network loopback``
    The same agents, clients and controller as separate local processes on
    127.0.0.1, with no emulated links. Needs nothing but the core package, on
    any OS. It is the smoke test for the live code paths, not a substitute for
    a Mininet run.

Either way the recording validates and scores like a simulated one::

    sudo .venv/bin/python -m turncoat_mininet.run --scenario sybil --onset 20 -o live.jsonl
    turncoat validate live.jsonl
    turncoat score live.jsonl

Attackers are placed exactly as ``turncoat run`` places them: the scenario's
own, plus any ``--attack`` spec, with onsets from ``--onset`` or the spec.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from turncoat_mininet import topology
from turncoat_mininet.addressing import AGENT_PORT, CX_IP, iot_ip, srv_ip
from turncoat_mininet.controller import Device, LiveController, Server
from turncoat_sdn.attacks import ServerAttack
from turncoat_sdn.cli.attack_spec import AttackSpecError, parse_attack, place_attacks
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter
from turncoat_sdn.sim import SCENARIOS, SimConfig

logger = logging.getLogger("turncoat_mininet.run")

#: Seconds between launching the processes and the run's ``t0``, so every
#: agent is listening and every client is waiting when the clock starts.
#: ``--warmup`` overrides it; the run refuses to start late rather than skew.
WARMUP_S = 8.0
API_PORT = 8081
LOOPBACK_AGENT_BASE_PORT = 18000


def build_config(args: argparse.Namespace) -> SimConfig:
    return replace(
        SimConfig(),
        n_nodes=args.servers,
        sim_s=args.duration,
        attack_start_s=args.onset,
        load_factor=args.load,
    )


def place(args: argparse.Namespace, config: SimConfig) -> dict[int, ServerAttack]:
    """The run's server attackers, placed as ``turncoat run`` places them."""
    specs = [parse_attack(text) for text in args.attack]
    attacks, client_attacks = place_attacks(specs, args.scenario, config)
    if client_attacks:
        raise AttackSpecError(
            "client attacks (spoof) are not supported by the live backend yet; "
            "use the simulator for them"
        )
    return attacks


def wait_until_up(urls: Sequence[str], timeout_s: float = 20.0) -> list[str]:
    """Poll each agent's ``/status`` until it answers. Returns the ones that never did."""
    deadline = time.time() + timeout_s
    pending = list(urls)
    while pending and time.time() < deadline:
        still = []
        for url in pending:
            try:
                with urllib.request.urlopen(f"{url}/status", timeout=0.5):
                    pass
            except OSError:
                still.append(url)
        pending = still
        if pending:
            time.sleep(0.2)
    return pending


def _summary(ctrl: LiveController, path: Path) -> dict[str, Any]:
    t = ctrl.totals
    return {
        "recording": str(path),
        "offered": t.offered,
        "completed": t.completed,
        "timed_out": t.timed_out,
        "failed": t.failed,
        "denied": t.denied,
        "polls": t.polls,
        "quarantines": t.quarantines,
        "served": t.served,
    }


class StartupError(RuntimeError):
    """The run could not start on time. Its recording holds only the header."""


def drive(
    args: argparse.Namespace,
    config: SimConfig,
    attacks: dict[int, ServerAttack],
    out: Path,
    *,
    servers: list[Server],
    launch_agent: Callable[[int, list[str]], None],
    launch_client: Callable[[int, list[str]], None],
    api_host: str,
    client_controller_url: str,
    devices: list[Device],
    agent_host: str = "0.0.0.0",
    agent_port: Callable[[int], int] = lambda i: AGENT_PORT,
    links: Sequence[dict[str, Any]] = (),
    switches: Sequence[dict[str, str]] = (),
    header: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start every process against one ``t0``, run the controller, and record.

    Agents start first and must answer ``/status``; then the controller's API
    opens and the clients start and say hello. If anything is not ready by
    ``t0``, the run stops with :class:`StartupError` rather than record a run
    whose clocks disagree or whose first seconds are missing.
    """
    t0 = time.time() + args.warmup
    for i, _ in enumerate(servers, start=1):
        argv = topology.agent_command(
            i,
            attacks.get(i - 1),
            t0=t0,
            seed=args.seed,
            config=config,
            host=agent_host,
            port=agent_port(i),
            work=args.work,
        )
        launch_agent(i, argv)
    down = wait_until_up([s.url for s in servers], timeout_s=max(0.5, t0 - time.time()))
    if down:
        raise StartupError(f"agents not answering by the start: {down}; see {args.logs}")

    with EventWriter(
        out,
        backend="live",
        seed=args.seed,
        strategy=args.strategy,
        scenario=args.scenario,
        **(header or {}),
    ) as rec:
        ctrl = LiveController(
            servers,
            rec,
            strategy=args.strategy,
            seed=args.seed,
            config=config,
            attacks=attacks,
            devices=devices,
            links=links,
            switches=switches,
        )
        api = ctrl.serve(api_host, args.api_port)
        threading.Thread(target=api.serve_forever, name="api", daemon=True).start()
        try:
            rate = config.arrival_rate / len(devices)
            for j, _ in enumerate(devices, start=1):
                argv = topology.client_command(
                    j,
                    controller=client_controller_url,
                    rate_hz=rate,
                    duration_s=args.duration,
                    t0=t0,
                    seed=args.seed,
                    config=config,
                )
                launch_client(j, argv)
            while len(ctrl.ready) < len(devices) and time.time() < t0:
                time.sleep(0.05)
            missing = sorted({d.id for d in devices} - ctrl.ready)
            late = time.time() - t0
            if missing:
                shown = ", ".join(missing[:5]) + (", ..." if len(missing) > 5 else "")
                raise StartupError(
                    f"{len(missing)} client(s) not ready by the start ({shown}); "
                    f"see {args.logs}, or raise --warmup"
                )
            if late > 0.25:
                raise StartupError(
                    f"processes took {late:.1f} s longer than --warmup {args.warmup:g} to "
                    "start; raise --warmup"
                )
            time.sleep(max(0.0, t0 - time.time()))
            ctrl.start(t0=t0)
            logger.info(
                "run started: %g s, %d servers, %d clients",
                args.duration,
                len(servers),
                len(devices),
            )
            time.sleep(max(0.0, t0 + args.duration - time.time()))
        finally:
            ctrl.stop()
            api.shutdown()
            api.server_close()
    return _summary(ctrl, out)


def run_loopback(
    args: argparse.Namespace, config: SimConfig, attacks: dict[int, ServerAttack], out: Path
) -> dict[str, Any]:
    plan = topology.plan_topology(args.servers, args.clients, args.seed)
    logs = Path(args.logs)
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(topology.BACKEND_ROOT), env.get("PYTHONPATH", "")) if p
    )
    procs: list[subprocess.Popen] = []
    handles: list[Any] = []

    def spawn(argv: list[str], log_name: str) -> None:
        log = open(logs / log_name, "w")  # noqa: SIM115 -- closed in the finally below
        handles.append(log)
        procs.append(subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env))

    def port(i: int) -> int:
        return args.agent_base_port + i

    try:
        return drive(
            args,
            config,
            attacks,
            out,
            servers=[
                Server(f"srv{i}", f"http://127.0.0.1:{port(i)}") for i in range(1, args.servers + 1)
            ],
            launch_agent=lambda i, argv: spawn(argv, f"srv{i}_agent.log"),
            launch_client=lambda j, argv: spawn(argv, f"iot{j}_client.log"),
            api_host="127.0.0.1",
            client_controller_url=f"http://127.0.0.1:{args.api_port}",
            devices=[Device(c) for c in plan.clients],
            agent_host="127.0.0.1",
            agent_port=port,
            header={"network": "loopback"},
        )
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for h in handles:
            h.close()


def run_mininet(
    args: argparse.Namespace, config: SimConfig, attacks: dict[int, ServerAttack], out: Path
) -> dict[str, Any]:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise RuntimeError("the Mininet network needs root: run this command with sudo")
    if not topology.mininet_available():
        raise RuntimeError(
            "Mininet is not importable from this Python. Install it (sudo apt install "
            "mininet openvswitch-switch) and create the virtual environment with "
            "--system-site-packages; see INSTALL.md"
        )
    from mininet.clean import cleanup

    plan = topology.plan_topology(args.servers, args.clients, args.seed)
    of = None
    if args.of_controller:
        host, _, port = args.of_controller.partition(":")
        of = (host, int(port or 6653))
    logs = Path(args.logs)
    logs.mkdir(parents=True, exist_ok=True)

    cleanup()
    net = topology.build_network(plan, of)
    net.start()
    try:
        topology.add_cx_node(net)
        loss = topology.check_reachability(net, plan)
        if loss > 0:
            logger.warning("reachability loss %.1f%%: the run may fail tasks for that", loss)

        def launch(host: str, argv: list[str], log_name: str) -> None:
            net.get(host).cmd(topology.shell_line(argv, str(logs / log_name)))

        return drive(
            args,
            config,
            attacks,
            out,
            servers=[
                Server(f"srv{i}", f"http://{srv_ip(i)}:{AGENT_PORT}")
                for i in range(1, args.servers + 1)
            ],
            launch_agent=lambda i, argv: launch(f"srv{i}", argv, f"srv{i}_agent.log"),
            launch_client=lambda j, argv: launch(f"iot{j}", argv, f"iot{j}_client.log"),
            api_host="0.0.0.0",
            client_controller_url=f"http://{CX_IP}:{args.api_port}",
            devices=[Device(c, iot_ip(int(c[3:]))) for c in plan.clients],
            links=[link.as_event() for link in plan.links],
            switches=plan.switch_nodes(),
            header={"network": "mininet", "reachability_loss": loss},
        )
    finally:
        topology.stop_processes(net, plan)
        net.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m turncoat_mininet.run",
        description="Run one live turncoat-sdn experiment and record it to events.jsonl.",
    )
    parser.add_argument("--network", choices=("mininet", "loopback"), default="mininet")
    parser.add_argument("--strategy", choices=list(STRATEGIES), default="zt_sdn")
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="sybil")
    parser.add_argument(
        "--attack",
        action="append",
        default=[],
        metavar="SPEC",
        help="add a server attacker, as for turncoat run (e.g. grayhole,node=srv2,start=20)",
    )
    parser.add_argument("--onset", type=float, default=0.0, help="attack onset, seconds")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--duration", type=float, default=60.0, help="run length, seconds")
    parser.add_argument("--servers", type=int, default=4)
    parser.add_argument("--clients", type=int, default=12)
    parser.add_argument(
        "--load",
        type=float,
        default=SimConfig.load_factor,
        help="offered load as a fraction of farm capacity (default %(default)s)",
    )
    parser.add_argument("--work", choices=("sleep", "burn"), default="sleep")
    parser.add_argument(
        "--warmup",
        type=float,
        default=WARMUP_S,
        help="seconds allowed for every agent and client to start (default %(default)s)",
    )
    parser.add_argument(
        "--of-controller",
        metavar="HOST:PORT",
        default=None,
        help="use this OpenFlow controller instead of standalone switches (mininet only)",
    )
    parser.add_argument(
        "--api-port", type=int, default=API_PORT, help="controller API port (default %(default)s)"
    )
    parser.add_argument(
        "--agent-base-port",
        type=int,
        default=LOOPBACK_AGENT_BASE_PORT,
        help="loopback only: srvN's agent listens on this plus N (default %(default)s)",
    )
    parser.add_argument("--logs", default="logs", help="directory for agent and client logs")
    parser.add_argument("-o", "--output", default="live.jsonl", help="recording to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    config = build_config(args)
    try:
        attacks = place(args, config)
    except AttackSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.output)
    runner = run_mininet if args.network == "mininet" else run_loopback
    try:
        summary = runner(args, config, attacks, out)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
