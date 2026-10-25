"""The edge-server agent: honest until the onset, then what its attack says.

Ported from the final-year project's ``tests/test_node_agent.py``. The project
tested the agent's own ``--malicious`` branches; the agent now holds a core
``ServerAttack``, so these tests check that it asks the attack the same two
questions the simulator does and acts on the answers over real HTTP.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest
from turncoat_mininet import node_agent
from turncoat_mininet.node_agent import NodeAgent, build_attack, build_parser

from turncoat_sdn.attacks import Blackhole, Grayhole, OnOff, Sybil
from turncoat_sdn.cli.attack_spec import SERVER_ATTACKS
from turncoat_sdn.sim import SimConfig

FAST = replace(SimConfig(), task_timeout_s=0.3)


class Clock:
    """A settable wall clock, so tests can step across an onset."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def serve_agent(free_port):
    """Start an agent's HTTP server on 127.0.0.1 and return its base URL."""
    servers = []

    def start(agent: NodeAgent) -> str:
        port = free_port()
        server = node_agent.serve(agent, "127.0.0.1", port)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as reply:
        return json.loads(reply.read())


def _post(url: str, body: dict, timeout: float = 5) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.status, json.loads(reply.read())


class TestBuildAttack:
    def test_none_is_an_honest_node(self):
        assert build_attack("none") is None

    @pytest.mark.parametrize(
        ("name", "cls"),
        [
            ("sybil", Sybil),
            ("blackhole", Blackhole),
            ("drop", Blackhole),
            ("grayhole", Grayhole),
            ("onoff", OnOff),
        ],
    )
    def test_every_attack_name_builds_the_core_attack(self, name, cls):
        attack = build_attack(name, 12.5)
        assert type(attack) is cls
        assert attack.start_s == 12.5

    def test_settings_come_from_the_simulator_config(self):
        cfg = replace(SimConfig(), sybil_claimed_cpu=0.05, sybil_rtt_ms=300.0)
        attack = build_attack("sybil", 0.0, cfg)
        assert (attack.claimed_cpu, attack.rtt_ms) == (0.05, 300.0)

    def test_unknown_name_is_refused(self):
        with pytest.raises(ValueError, match="unknown attack"):
            build_attack("wormhole")

    def test_the_names_match_turncoat_run(self):
        # Kept apart from turncoat_sdn.cli so agents start fast; this keeps them in step.
        assert node_agent.ATTACKS == SERVER_ATTACKS

    def test_the_agent_does_not_import_the_cli(self):
        import subprocess
        import sys

        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); import turncoat_mininet.node_agent; "
            "print('turncoat_sdn.cli' in sys.modules, 'scipy' in sys.modules)"
        )
        root = str(Path(node_agent.__file__).resolve().parent.parent)
        out = subprocess.run(
            [sys.executable, "-c", script, root], capture_output=True, text=True, check=True
        )
        assert out.stdout.split() == ["False", "False"]

    def test_the_cli_accepts_every_server_attack(self):
        for name in ["none", *SERVER_ATTACKS]:
            args = build_parser().parse_args(["--node-id", "srv1", "--attack", name])
            assert args.attack == name


class TestStatus:
    def test_honest_node_reports_its_occupancy_and_answers_at_once(self):
        agent = NodeAgent("srv1")
        agent.busy, agent.queued = 2, 1
        body, delay = agent.status()
        assert body["cpu_load"] == 0.75
        assert (body["active_tasks"], body["queued"], body["concurrency"]) == (2, 1, 4)
        assert delay == 0.0

    def test_sybil_before_its_onset_reports_the_truth(self):
        clock = Clock()
        agent = NodeAgent("srv4", build_attack("sybil", 30.0), t0=clock.t, clock=clock)
        agent.busy = 4
        clock.t += 29.9
        body, delay = agent.status()
        assert body["cpu_load"] == 1.0
        assert delay == 0.0

    def test_sybil_after_its_onset_lies_and_answers_slowly(self):
        clock = Clock()
        agent = NodeAgent("srv4", build_attack("sybil", 30.0), t0=clock.t, clock=clock)
        agent.busy = 4
        clock.t += 30.0
        body, delay = agent.status()
        assert body["cpu_load"] == 0.1
        # 220 ms in all; the healthy 50 ms is the network's to supply.
        assert delay == pytest.approx(0.170)

    def test_onoff_is_honest_between_hostile_phases(self):
        clock = Clock()
        agent = NodeAgent("srv4", build_attack("onoff", 10.0), t0=clock.t, clock=clock)
        agent.busy = 4
        clock.t += 12.0  # 2 s into the first 10 s hostile phase
        assert agent.status()[0]["cpu_load"] == 0.1
        clock.t += 10.0  # 2 s into the following honest phase
        body, delay = agent.status()
        assert body["cpu_load"] == 1.0
        assert delay == 0.0


class TestServe:
    def test_honest_node_serves_every_task(self):
        agent = NodeAgent("srv1", config=FAST)
        assert all(agent.run_task(0.0) for _ in range(5))
        assert (agent.served, agent.dropped) == (5, 0)

    def test_blackhole_serves_before_its_onset_and_drops_after(self):
        clock = Clock()
        agent = NodeAgent("srv3", Blackhole(5.0), t0=clock.t, config=FAST, clock=clock)
        assert agent.run_task(0.0)
        clock.t += 5.0
        started = time.perf_counter()
        assert not agent.run_task(0.0)
        # The worker is held until the client has given up, as in the simulator.
        assert time.perf_counter() - started >= FAST.task_timeout_s * 0.9

    def test_grayhole_drops_roughly_its_fraction(self):
        agent = NodeAgent("srv2", Grayhole(0.0, drop_fraction=0.5), config=FAST)
        agent.config = replace(FAST, task_timeout_s=0.0)
        served = sum(agent.run_task(0.0) for _ in range(200))
        assert 70 <= served <= 130

    def test_same_seed_drops_the_same_tasks(self):
        def pattern(seed):
            agent = NodeAgent(
                "srv2",
                Grayhole(0.0),
                seed=seed,
                config=replace(FAST, task_timeout_s=0.0),
            )
            return [agent.run_task(0.0) for _ in range(40)]

        assert pattern(7) == pattern(7)
        assert pattern(7) != pattern(8)

    def test_sybil_serves_slowly_once_it_turns(self):
        agent = NodeAgent("srv4", build_attack("sybil", 0.0), config=FAST)
        started = time.perf_counter()
        agent.run_task(0.05)
        assert time.perf_counter() - started >= 0.09  # twice the demand

    def test_no_more_than_concurrency_tasks_run_at_once(self):
        agent = NodeAgent("srv1", config=replace(FAST, concurrency=2))
        peak = []

        def task():
            agent.run_task(0.1)

        threads = [threading.Thread(target=task) for _ in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.05)
        peak.append((agent.busy, agent.queued))
        for t in threads:
            t.join()
        assert peak[0] == (2, 3)

    def test_burn_mode_spends_the_service_time_hashing(self, monkeypatch):
        burned, slept = [], []
        monkeypatch.setattr(node_agent, "_burn", burned.append)
        monkeypatch.setattr(node_agent.time, "sleep", slept.append)
        NodeAgent("srv1", config=FAST, work="burn").run_task(0.05)
        assert (burned, slept) == ([0.05], [])

    def test_burn_hashes_for_the_whole_time(self):
        started = time.perf_counter()
        node_agent._burn(0.03)
        assert time.perf_counter() - started >= 0.03

    def test_unknown_work_mode_is_refused(self):
        with pytest.raises(ValueError, match="work must be"):
            NodeAgent("srv1", work="nap")


class TestHttp:
    def test_status_and_task_endpoints(self, serve_agent):
        url = serve_agent(NodeAgent("srv1", config=FAST))
        status = _get(f"{url}/status")
        assert status["node_id"] == "srv1"
        assert status["cpu_load"] == 0.0
        assert _post(f"{url}/task", {"task": 1, "demand_s": 0.01}) == (
            200,
            {"ok": True, "node_id": "srv1"},
        )

    def test_a_dropped_task_gets_no_reply(self, serve_agent):
        url = serve_agent(NodeAgent("srv3", Blackhole(0.0), config=FAST))
        with pytest.raises((urllib.error.URLError, OSError)):
            _post(f"{url}/task", {"task": 1, "demand_s": 0.01}, timeout=2)

    def test_a_sybil_answers_polls_slowly(self, serve_agent):
        url = serve_agent(NodeAgent("srv4", build_attack("sybil", 0.0), config=FAST))
        started = time.perf_counter()
        assert _get(f"{url}/status")["cpu_load"] == 0.1
        assert time.perf_counter() - started >= 0.15

    @pytest.mark.parametrize("body", [b"not json", b'{"demand_s": "soon"}', b'{"demand_s": -1}'])
    def test_a_bad_task_body_is_a_400(self, serve_agent, body):
        url = serve_agent(NodeAgent("srv1", config=FAST))
        request = urllib.request.Request(f"{url}/task", data=body, method="POST")
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(request, timeout=5)
        err.value.close()
        assert err.value.code == 400

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_unknown_paths_are_404(self, serve_agent, method):
        url = serve_agent(NodeAgent("srv1", config=FAST))
        data = b"{}" if method == "POST" else None
        request = urllib.request.Request(f"{url}/nope", data=data, method=method)
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(request, timeout=5)
        err.value.close()
        assert err.value.code == 404
