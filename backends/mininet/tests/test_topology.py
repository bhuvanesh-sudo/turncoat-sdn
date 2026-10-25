"""The live network plan and the commands that launch it, checked without Mininet.

Ported from the final-year project's ``tests/test_live_config_preflight.py``
and the reachability and teardown parts of ``tests/test_run_demo_mininet.py``.
The preflight's point carries over: every command the topology would run must
parse with the program it starts, and every attacker in the ground truth must
really be launched attacking, from the same onset.
"""

from __future__ import annotations

import shlex
from dataclasses import replace

import pytest
from turncoat_mininet import iot_client, node_agent, topology
from turncoat_mininet.addressing import iot_ip, iot_mac, srv_index, srv_ip, srv_mac
from turncoat_mininet.controller import Server, topology_graph

from turncoat_sdn.cli.attack_spec import parse_attack, place_attacks
from turncoat_sdn.sim import SimConfig, client_ip


class TestAddressing:
    def test_iot_addresses_match_the_simulator(self):
        assert [iot_ip(j + 1) for j in range(40)] == [client_ip(j) for j in range(40)]

    def test_addresses_are_distinct_per_host(self):
        assert len({srv_ip(i) for i in range(1, 9)} | {iot_ip(j) for j in range(1, 41)}) == 48
        assert len({srv_mac(i) for i in range(1, 9)} | {iot_mac(j) for j in range(1, 41)}) == 48

    def test_srv_index(self):
        assert srv_index("srv12") == 12
        with pytest.raises(ValueError):
            srv_index("iot3")


class TestPlan:
    def test_three_tier_shape(self):
        plan = topology.plan_topology(4, 12, seed=1)
        assert plan.switches == ("s0", "s1", "s2", "s3", "s4")
        assert plan.servers == ("srv1", "srv2", "srv3", "srv4")
        assert len(plan.clients) == 12
        # Server link, core link per edge switch; one link per device.
        assert len(plan.links) == 2 * 4 + 12

    def test_devices_attach_round_robin(self):
        plan = topology.plan_topology(4, 12, seed=1)
        assert [plan.client_switch[f"iot{j}"] for j in range(1, 6)] == [
            "s1",
            "s2",
            "s3",
            "s4",
            "s1",
        ]

    def test_fixed_link_parameters(self):
        links = {(link.a, link.b): link for link in topology.plan_topology(2, 2).links}
        assert (links[("s1", "srv1")].delay_ms, links[("s1", "srv1")].bw_mbps) == (2, 100)
        assert (links[("s0", "s1")].delay_ms, links[("s0", "s1")].bw_mbps) == (5, 1000)

    def test_device_delays_are_seeded(self):
        def delays(seed):
            return [link.delay_ms for link in topology.plan_topology(8, 40, seed).links]

        assert delays(3) == delays(3)
        assert delays(3) != delays(4)
        assert all(1 <= d <= 10 for d in delays(3)[16:])

    @pytest.mark.parametrize(("servers", "clients"), [(0, 4), (4, 0), (251, 4)])
    def test_sizes_out_of_range_are_refused(self, servers, clients):
        with pytest.raises(ValueError):
            topology.plan_topology(servers, clients)

    def test_switches_carry_no_ground_truth(self):
        nodes = topology.plan_topology(2, 2).switch_nodes()
        assert nodes[0] == {"id": "s0", "kind": "core_switch"}
        assert all("attack" not in n for n in nodes)


class TestReachabilitySample:
    def test_probe_count_is_linear(self):
        plan = topology.plan_topology(8, 40)
        assert len(topology.reachability_pairs(plan)) == 48

    def test_every_host_is_probed(self):
        plan = topology.plan_topology(8, 40)
        probed = {h for pair in topology.reachability_pairs(plan) for h in pair}
        assert probed == set(plan.servers) | set(plan.clients)

    def test_loss_is_reported(self):
        plan = topology.plan_topology(2, 2)
        net = FakeNet(plan, unreachable={"10.0.1.2"})
        assert topology.check_reachability(net, plan) == 25.0


# --- Preflight: what would be launched -----------------------------------------


def _launch(scenario="both", specs=(), onset=20.0, servers=4, clients=6):
    config = replace(SimConfig(), n_nodes=servers, attack_start_s=onset)
    attacks, _ = place_attacks([parse_attack(s) for s in specs], scenario, config)
    agents = [
        topology.agent_command(i, attacks.get(i - 1), t0=1e9, seed=3, config=config)
        for i in range(1, servers + 1)
    ]
    devices = [
        topology.client_command(
            j,
            controller="http://10.0.99.254:8081",
            rate_hz=2.5,
            duration_s=60,
            t0=1e9,
            seed=3,
            config=config,
        )
        for j in range(1, clients + 1)
    ]
    return attacks, agents, devices


class TestLaunchCommandsParse:
    def test_every_agent_and_client_command_parses(self):
        _, agents, devices = _launch()
        for argv in agents:
            assert argv[1:3] == ["-m", "turncoat_mininet.node_agent"]
            node_agent.build_parser().parse_args(argv[3:])
        for argv in devices:
            assert argv[1:3] == ["-m", "turncoat_mininet.iot_client"]
            iot_client.build_parser().parse_args(argv[3:])

    def test_every_server_and_device_is_launched(self):
        _, agents, devices = _launch(servers=5, clients=7)
        ids = [node_agent.build_parser().parse_args(a[3:]).node_id for a in agents]
        devs = [iot_client.build_parser().parse_args(a[3:]).device_id for a in devices]
        assert ids == [f"srv{i}" for i in range(1, 6)]
        assert devs == [f"iot{j}" for j in range(1, 8)]

    def test_settings_reach_the_agent(self):
        _, agents, _ = _launch()
        args = node_agent.build_parser().parse_args(agents[0][3:])
        assert (args.t0, args.seed, args.concurrency, args.task_timeout_s) == (1e9, 3, 4, 2.0)


class TestGroundTruthMatchesWhatIsLaunched:
    @pytest.mark.parametrize(
        ("scenario", "specs"),
        [
            ("both", ()),
            ("grayhole", ()),
            ("onoff", ()),
            ("clean", ("sybil,node=srv1,start=5", "blackhole,node=srv2")),
        ],
    )
    def test_every_attacker_is_launched_attacking_from_its_onset(self, scenario, specs):
        attacks, agents, _ = _launch(scenario, specs)
        graph = topology_graph([Server(f"srv{i}", "") for i in range(1, 5)], attacks)
        truth = {n["id"]: n for n in graph["nodes"]}
        for argv in agents:
            args = node_agent.build_parser().parse_args(argv[3:])
            node = truth[args.node_id]
            launched = node_agent.build_attack(args.attack, args.start_s)
            if node["attack"] == "none":
                assert launched is None
            else:
                assert launched.name == node["attack"]
                assert args.start_s == node["attack_start_s"]

    def test_attackers_sit_where_the_simulator_puts_them(self):
        attacks, agents, _ = _launch("both")
        launched = {
            a.node_id: a.attack
            for a in (node_agent.build_parser().parse_args(x[3:]) for x in agents)
        }
        assert launched == {"srv1": "none", "srv2": "none", "srv3": "drop", "srv4": "sybil"}


class TestShellLine:
    def test_backgrounds_and_logs(self):
        line = topology.shell_line(["python3", "-m", "x", "--a", "b c"], "logs/srv1.log")
        assert line.endswith("> logs/srv1.log 2>&1 &")
        assert "'b c'" in line

    def test_puts_the_backend_on_pythonpath(self):
        line = topology.shell_line(["python3"], "x.log")
        assert line.startswith(f"PYTHONPATH={shlex.quote(str(topology.BACKEND_ROOT))}")


class TestTeardown:
    def test_every_agent_and_client_is_killed(self):
        plan = topology.plan_topology(2, 3)
        net = FakeNet(plan)
        topology.stop_processes(net, plan)
        killed = {name for name, cmd in net.commands if cmd.startswith("pkill")}
        assert killed == {"srv1", "srv2", "iot1", "iot2", "iot3"}


class TestMininetIsOptional:
    def test_topology_imports_without_mininet(self):
        # Importing it already happened above; this pins that nothing here
        # needs Mininet unless a network is actually built.
        assert callable(topology.plan_topology)

    @pytest.mark.skipif(topology.mininet_available(), reason="Mininet is installed here")
    def test_building_a_network_without_mininet_fails_clearly(self):
        with pytest.raises(ImportError):
            topology.build_network(topology.plan_topology(1, 1))


class FakeHost:
    def __init__(self, net: FakeNet, name: str, ip: str) -> None:
        self.net, self.name, self.ip = net, name, ip

    def IP(self) -> str:  # noqa: N802 -- Mininet's name
        return self.ip

    def cmd(self, command: str) -> str:
        self.net.commands.append((self.name, command))
        if command.startswith("ping"):
            target = command.split()[-1]
            loss = "100%" if target in self.net.unreachable else "0%"
            return f"1 packets transmitted, {loss} packet loss"
        return ""


class FakeNet:
    def __init__(self, plan: topology.Plan, unreachable: set[str] = frozenset()) -> None:
        self.unreachable = unreachable
        self.commands: list[tuple[str, str]] = []
        self.hosts = {s: FakeHost(self, s, srv_ip(int(s[3:]))) for s in plan.servers}
        self.hosts |= {c: FakeHost(self, c, iot_ip(int(c[3:]))) for c in plan.clients}

    def get(self, name: str) -> FakeHost:
        return self.hosts[name]
