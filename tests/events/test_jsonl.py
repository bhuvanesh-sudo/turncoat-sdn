"""The JSONL writer and reader, ported from ``controller/event_bus.py`` and ``load_events``.

The final-year project's ``tests/test_event_bus.py`` mostly guards the
dashboard fan-out, which stayed behind. The recording tests come across here:
events are written as replayable JSONL, concurrent publishers don't corrupt
the file, and a killed run leaves a readable file. ``load_events``' tolerance
of a truncated tail line is kept by :func:`read_events`.
"""

from __future__ import annotations

import json
import math
import threading

import pytest

from turncoat_sdn.events import SCHEMA_VERSION, EventWriter, read_events, supported_version
from turncoat_sdn.events.validate import validate_file


def _lines(path):
    return path.read_text("utf-8").splitlines()


class TestEventWriter:
    def test_first_line_is_the_header(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="sim", seed=7, strategy="zt_sdn", scenario="on-off"):
            pass

        assert [json.loads(line) for line in _lines(path)] == [
            {
                "type": "header",
                "schema_version": SCHEMA_VERSION,
                "backend": "sim",
                "seed": 7,
                "strategy": "zt_sdn",
                "scenario": "on-off",
            }
        ]

    def test_header_leaves_out_what_was_not_given_and_keeps_extras(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="live", testbed="mininet-8-40") as rec:
            header = rec.header

        assert header == {
            "type": "header",
            "schema_version": SCHEMA_VERSION,
            "backend": "live",
            "testbed": "mininet-8-40",
        }

    def test_events_are_recorded_as_replayable_jsonl(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="sim") as rec:
            written = rec.write("route", 1.5, chosen="srv2", edge_score=0.81)
            rec.write("quarantine", 2.0, node="srv3")

        assert written == {"type": "route", "ts": 1.5, "chosen": "srv2", "edge_score": 0.81}
        lines = _lines(path)
        assert len(lines) == 3
        assert json.loads(lines[1]) == written
        assert json.loads(lines[2])["node"] == "srv3"

    def test_round_trips_through_the_reader(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="sim") as rec:
            sent = [
                rec.write("report", float(i), node="srv1", status="success", latency_ms=i)
                for i in range(3)
            ]

        events = read_events(path)
        assert events[0]["type"] == "header"
        assert events[1:] == sent

    def test_each_event_is_on_disk_before_close(self, tmp_path):
        # Line-buffered: a run killed with Ctrl-C still leaves every event it
        # wrote, not a file that lost its tail in an unflushed buffer.
        path = tmp_path / "run.jsonl"
        rec = EventWriter(path, backend="sim")
        try:
            rec.write("route", 0.5, chosen="srv1")
            assert len(_lines(path)) == 2
        finally:
            rec.close()

    def test_creates_missing_parent_directories(self, tmp_path):
        path = tmp_path / "runs" / "seed-7" / "events.jsonl"
        with EventWriter(path, backend="sim"):
            pass
        assert path.is_file()

    def test_refuses_nan_rather_than_writing_invalid_json(self, tmp_path):
        with EventWriter(tmp_path / "run.jsonl", backend="sim") as rec:
            with pytest.raises(ValueError):
                rec.write("anomaly", 1.0, node="srv1", signals={"latency_tell": math.nan})

    def test_refuses_a_type_field(self, tmp_path):
        with EventWriter(tmp_path / "run.jsonl", backend="sim") as rec:
            with pytest.raises(ValueError, match="event_type"):
                rec.write("route", 1.0, type="report")

    def test_refuses_to_write_after_close(self, tmp_path):
        rec = EventWriter(tmp_path / "run.jsonl", backend="sim")
        rec.close()
        rec.close()  # closing twice is harmless
        with pytest.raises(ValueError, match="closed"):
            rec.write("route", 1.0, chosen="srv1")

    def test_concurrent_writers_never_interleave_lines(self, tmp_path):
        """A live backend records from the OpenFlow thread, the poll loop and
        the REST handlers at once; every line must still be one whole event."""
        path = tmp_path / "run.jsonl"
        rec = EventWriter(path, backend="live")

        def write_many(worker):
            for i in range(200):
                rec.write("report", 1.0, node=f"srv{worker}", status="success", latency_ms=i)

        threads = [threading.Thread(target=write_many, args=(w,)) for w in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rec.close()

        events = [json.loads(line) for line in _lines(path)]
        assert len(events) == 801
        for worker in range(4):
            mine = [e["latency_ms"] for e in events if e.get("node") == f"srv{worker}"]
            assert mine == list(range(200))

    def test_a_recording_it_writes_passes_the_validator(self, tmp_path):
        path = tmp_path / "run.jsonl"
        with EventWriter(path, backend="sim", seed=1) as rec:
            rec.write(
                "topology",
                0.0,
                graph={"nodes": [{"id": "srv1", "kind": "server", "attack": "none"}]},
            )
            rec.write("route", 0.2, chosen="srv1", task=1)
            rec.write("report", 0.3, node="srv1", status="success", latency_ms=12.5, task=1)

        report = validate_file(path)
        assert report.ok, report.format(str(path))


class TestReadEvents:
    def test_reads_the_sample_header_first(self, sample_path):
        events = read_events(sample_path)
        assert events[0] == {
            "type": "header",
            "schema_version": "1.0",
            "backend": "sim",
            "seed": 7,
            "strategy": "zt_sdn",
            "scenario": "on-off",
        }
        assert len(events) == 12

    def test_skips_blank_lines_and_a_truncated_tail(self, tmp_path):
        # A run killed mid-write leaves one cut-off last line; the scorers must
        # still grade everything before it.
        path = tmp_path / "run.jsonl"
        path.write_text(
            '{"type": "header", "schema_version": "1.0", "backend": "sim"}\n'
            "\n"
            '{"type": "route", "ts": 1.0, "chosen": "srv1"}\n'
            '{"type": "report", "ts": 1.2, "node": "sr',
            encoding="utf-8",
        )
        assert [e["type"] for e in read_events(path)] == ["header", "route"]

    def test_skips_json_that_is_not_an_event(self, tmp_path):
        path = tmp_path / "run.jsonl"
        path.write_text('[1, 2]\n"text"\n{"type": "route", "ts": 1.0}\n', encoding="utf-8")
        assert read_events(path) == [{"type": "route", "ts": 1.0}]


class TestSupportedVersion:
    @pytest.mark.parametrize("version", ["1.0", "1.1", "1.12", "1"])
    def test_any_1x_reads(self, version):
        assert supported_version(version)

    @pytest.mark.parametrize("version", ["0.9", "2.0", "10.0", ""])
    def test_other_majors_do_not(self, version):
        assert not supported_version(version)
