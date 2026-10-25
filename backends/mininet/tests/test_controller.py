"""The live controller: the simulator's decisions on real polls and real outcomes.

Polls go to a stand-in ``fetch_status`` so detection is exact and instant; one
test drives the real HTTP API end to end. Every recording is checked with the
core validator and scored with the core attack scorer, unchanged.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest
from turncoat_mininet.controller import Device, LiveController, Server, topology_graph

from turncoat_sdn.attacks import Blackhole, Sybil
from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import SIGNAL_LATENCY_TELL, SIGNAL_PACKET_DROP

SERVERS = [Server(f"srv{i}", f"http://srv{i}") for i in range(1, 5)]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class FakeFleet:
    """What each server answers at a poll, and how slowly."""

    def __init__(self) -> None:
        self.cpu = {s.id: 0.5 for s in SERVERS}
        self.delay_s = {s.id: 0.0 for s in SERVERS}
        self.down: set[str] = set()

    def __call__(self, server: Server):
        if server.id in self.down:
            return None
        time.sleep(self.delay_s[server.id])
        return {"node_id": server.id, "cpu_load": self.cpu[server.id]}


@pytest.fixture
def live(tmp_path):
    """A controller over four stand-in servers, recording to a temp file."""
    made = []

    def make(strategy="zt_sdn", attacks=None, devices=()):
        path = tmp_path / "live.jsonl"
        rec = EventWriter(path, backend="live", seed=1, strategy=strategy, scenario="test")
        clock, fleet = Clock(), FakeFleet()
        ctrl = LiveController(
            SERVERS,
            rec,
            strategy=strategy,
            attacks=attacks or {},
            devices=devices,
            clock=clock,
            fetch_status=fleet,
        )
        ctrl.start(poll=False)
        made.append((ctrl, rec))
        return ctrl, clock, fleet, path

    yield make
    for ctrl, rec in made:
        ctrl.stop()
        rec.close()


def _finish(ctrl, path):
    ctrl.stop()
    ctrl.rec.close()
    report = validate_file(path)
    assert report.ok, report.format(str(path))
    return read_events(path)


class TestTopology:
    def test_ground_truth_and_devices(self):
        graph = topology_graph(
            SERVERS[:2], {1: Sybil(15.0)}, [Device("iot1", "10.0.0.1"), Device("iot2")]
        )
        nodes = {n["id"]: n for n in graph["nodes"]}
        assert nodes["srv1"]["attack"] == "none"
        assert (nodes["srv2"]["attack"], nodes["srv2"]["attack_start_s"]) == ("sybil", 15.0)
        assert nodes["iot1"] == {"id": "iot1", "kind": "iot", "attack": "none", "ip": "10.0.0.1"}
        assert "ip" not in nodes["iot2"]

    def test_servers_must_be_in_index_order(self, tmp_path):
        with EventWriter(tmp_path / "x.jsonl", backend="live") as rec:
            with pytest.raises(ValueError, match="must be srv1"):
                LiveController([Server("srv2", "")], rec)

    def test_unknown_strategy_is_refused(self, tmp_path):
        with EventWriter(tmp_path / "x.jsonl", backend="live") as rec:
            with pytest.raises(ValueError, match="unknown strategy"):
                LiveController(SERVERS, rec, strategy="best")


class TestRouteAndReport:
    def test_route_then_report_is_recorded_and_moves_trust(self, live):
        ctrl, clock, _, path = live("round_robin")
        answer = ctrl.route("iot1", "10.0.0.1")
        assert (answer["task"], answer["node"], answer["url"]) == (1, "srv1", "http://srv1")
        assert answer["demand_s"] > 0
        before = ctrl.trust[0]
        clock.t = 0.3
        assert ctrl.report(1, "success", 250.0, "iot1")
        assert ctrl.trust[0] != before
        events = _finish(ctrl, path)
        route, report = events[2], events[3]
        assert route == {
            "type": "route",
            "ts": 0.0,
            "task": 1,
            "chosen": "srv1",
            "client_ip": "10.0.0.1",
        }
        assert (report["node"], report["status"], report["latency_ms"]) == ("srv1", "success", 250)

    def test_a_task_is_reported_once(self, live):
        ctrl, *_ = live("round_robin")
        task = ctrl.route()["task"]
        assert ctrl.report(task, "timeout", 2000.0)
        assert not ctrl.report(task, "success", 10.0)
        assert not ctrl.report(999, "success", 10.0)

    def test_a_failure_counts_as_a_timeout_for_trust(self, live):
        ctrl, *_ = live("round_robin")
        task = ctrl.route()["task"]
        ctrl.report(task, "failure", 3.0)
        assert list(ctrl.recent[0]) == ["timeout"]
        assert ctrl.totals.failed == 1

    def test_a_bad_status_is_refused(self, live):
        ctrl, *_ = live()
        with pytest.raises(ValueError):
            ctrl.report(1, "ok", 1.0)

    def test_demands_follow_the_seed(self, live):
        a, *_ = live("round_robin")
        b, *_ = live("round_robin")
        first = [a.route()["demand_s"] for _ in range(5)]
        assert first == [b.route()["demand_s"] for _ in range(5)]

    def test_nothing_is_routed_after_the_run(self, live):
        ctrl, *_ = live()
        ctrl.stop()
        assert ctrl.route() == {"denied": "run over"}


class TestDetection:
    def test_the_latency_tell_catches_a_slow_idle_claimer(self, live):
        ctrl, clock, fleet, path = live(attacks={3: Sybil(0.0)})
        fleet.cpu["srv4"], fleet.delay_s["srv4"] = 0.1, 0.12
        for k in range(1, 6):
            clock.t = float(k)
            ctrl.poll_once()
        assert ctrl.excluded == [False, False, False, True]
        events = _finish(ctrl, path)
        flagged = [e for e in events if e["type"] == "anomaly"]
        assert {e["node"] for e in flagged} == {"srv4"}
        assert SIGNAL_LATENCY_TELL in flagged[0]["signals"]
        assert [e["node"] for e in events if e["type"] == "quarantine"] == ["srv4"]
        assert sum(e["type"] == "node_status" for e in events) == 5
        verdicts = {r.subject: r.predicted for r in score_run(events)}
        assert verdicts["srv4"] == "sybil"

    def test_the_timeout_rate_tell_catches_a_dropper(self, live):
        ctrl, clock, _, path = live("round_robin", attacks={2: Blackhole(0.0)})
        for _ in range(24):
            answer = ctrl.route()
            status = "timeout" if answer["node"] == "srv3" else "success"
            ctrl.report(answer["task"], status, 2000.0 if status == "timeout" else 200.0)
        for k in range(1, 3):
            clock.t = float(k)
            ctrl.poll_once()
        assert ctrl.excluded[2]
        events = _finish(ctrl, path)
        drops = [e for e in events if e["type"] == "anomaly"]
        assert {e["node"] for e in drops} == {"srv3"}
        assert drops[0]["signals"][SIGNAL_PACKET_DROP] == 1.0

    def test_an_unanswered_poll_counts_as_slow(self, live):
        ctrl, clock, fleet, _ = live()
        fleet.down.add("srv2")
        clock.t = 1.0
        ctrl.poll_once()
        assert ctrl.rtt_ms[1] >= 800.0
        assert ctrl.claimed_cpu[1] == 0.0  # unchanged from the start

    def test_recovery_is_recorded(self, live):
        ctrl, clock, fleet, path = live(attacks={3: Sybil(0.0)})
        fleet.cpu["srv4"], fleet.delay_s["srv4"] = 0.1, 0.12
        for k in range(1, 5):
            clock.t = float(k)
            ctrl.poll_once()
        fleet.delay_s["srv4"] = 0.0
        for k in range(5, 12):
            clock.t = float(k)
            ctrl.poll_once()
        events = _finish(ctrl, path)
        edges = [e["type"] for e in events if e["type"] in ("quarantine", "recovered")]
        assert edges == ["quarantine", "recovered"]

    def test_zt_sdn_denies_when_every_server_is_out(self, live):
        ctrl, *_ = live()
        ctrl.anomaly[:] = [1.0] * 4
        assert ctrl.route()["denied"] == "all candidates quarantined"
        assert ctrl.totals.denied == 1


class TestStart:
    def test_the_clock_is_anchored_on_the_shared_start(self, tmp_path):
        with EventWriter(tmp_path / "x.jsonl", backend="live") as rec:
            ctrl = LiveController(SERVERS, rec, fetch_status=FakeFleet())
            ctrl.start(poll=False, t0=time.time() - 2.0)
            assert 1.9 <= ctrl.now() <= 3.0
            ctrl.stop()

    def test_hello_marks_a_device_ready(self, live):
        ctrl, *_ = live()
        ctrl.hello("iot3")
        assert ctrl.ready == {"iot3"}


class TestHttpApi:
    def test_route_report_and_health(self, live, free_port):
        ctrl, *_ = live("round_robin")
        port = free_port()
        api = ctrl.serve("127.0.0.1", port)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=5) as reply:
                assert json.loads(reply.read()) == {"ok": True, "running": True}
            assert _post(f"{base}/hello", {"device": "iot1"}) == {"ok": True}
            assert ctrl.ready == {"iot1"}
            answer = _post(f"{base}/route", {"device": "iot1"})
            assert answer["node"] == "srv1"
            done = {"task": answer["task"], "status": "success", "latency_ms": 12.5}
            assert _post(f"{base}/report", done) == {"accepted": True}
            with pytest.raises(urllib.error.HTTPError) as err:
                _post(f"{base}/report", {"task": 1})
            err.value.close()
            assert err.value.code == 400
        finally:
            api.shutdown()
            api.server_close()


def _post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=5) as reply:
        return json.loads(reply.read())
