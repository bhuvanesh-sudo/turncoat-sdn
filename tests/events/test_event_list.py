"""``EventList``: a recording kept in memory is exactly what reading the file back gives."""

from __future__ import annotations

from dataclasses import replace

import pytest

from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import SCHEMA_VERSION, EventList, EventWriter, read_events
from turncoat_sdn.sim import SimConfig, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = replace(SimConfig(), sim_s=20.0)


@pytest.mark.parametrize("scenario", ["both", "spoof"])
def test_matches_the_file(tmp_path, scenario):
    path = tmp_path / "run.jsonl"
    hooks = {"trust": SimTrustModel, "latency_tell": latency_tell, "config": SHORT}
    router = STRATEGIES["zt_sdn"]
    with EventWriter(path, backend="sim", seed=4, strategy="zt_sdn", scenario=scenario) as rec:
        simulate(router, scenario, 4, recorder=rec, **hooks)
    memory = EventList(backend="sim", seed=4, strategy="zt_sdn", scenario=scenario)
    simulate(router, scenario, 4, recorder=memory, **hooks)
    assert memory.events == read_events(path)


def test_header_first():
    memory = EventList(backend="sim", seed=1, run="a")
    assert memory.events == [
        {
            "type": "header",
            "schema_version": SCHEMA_VERSION,
            "backend": "sim",
            "seed": 1,
            "run": "a",
        }
    ]
    assert memory.header == memory.events[0]


def test_stores_what_a_file_would_hold():
    memory = EventList(backend="sim")
    stored = memory.write("topology", 0.0, graph={"links": ()})
    assert stored == {"type": "topology", "ts": 0.0, "graph": {"links": []}}
    assert memory.events[-1] is stored


def test_rejects_what_a_file_would_reject():
    memory = EventList(backend="sim")
    with pytest.raises(ValueError):
        memory.write("anomaly", 1.0, anomaly=float("nan"))
    with pytest.raises(ValueError, match="event_type"):
        memory.write("route", 1.0, type="report")
