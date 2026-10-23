"""The validator: a good recording passes, and a broken one says what is wrong, where.

Most cases take the valid sample, break one thing, and check that exactly one
problem comes back, with a message that points at the line and the field.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

from turncoat_sdn.events import schema
from turncoat_sdn.events.jsonl import read_events
from turncoat_sdn.events.validate import Problem, Report, main, validate_events, validate_file
from turncoat_sdn.scoring.attack_report import ground_truth, onset_times

DOC = Path(__file__).parents[2] / "docs" / "event-format.md"


def _problems(events):
    return [str(p) for p in validate_events(events).problems]


def _only_problem(events):
    problems = _problems(events)
    assert len(problems) == 1, problems
    return problems[0]


def _node(events, node_id):
    return next(n for n in events[1]["graph"]["nodes"] if n["id"] == node_id)


class TestDoneWhen:
    """The v0.2 task's acceptance condition, as written in the plan."""

    def test_the_sample_recording_passes(self, sample_path):
        report = validate_file(sample_path)
        assert report.ok, report.format("sample_run.jsonl")
        assert report.format("sample_run.jsonl") == (
            "sample_run.jsonl: valid, schema 1.0, 12 lines"
        )

    def test_a_broken_recording_fails_with_clear_messages(self, broken_path):
        report = validate_file(broken_path)
        assert not report.ok
        assert report.format("broken_run.jsonl").splitlines() == [
            "broken_run.jsonl: 5 problems",
            "  line 2 (topology): 'graph.nodes[1].attack_start_s' is required: "
            '"srv2" attacks ("grayhole"), and detection latency is measured from its onset',
            "  line 3 (route): 'chosen' names \"srv9\", which is not a server in the topology",
            "  line 4 (report): 'status' must be one of success, timeout, failure; got \"ok\"",
            "  line 5 (report): ts 3.9 is earlier than 4.5 on line 4; "
            "events must be appended in time order",
            "  line 6: not valid JSON: Unterminated string starting at column 51",
        ]


class TestHeader:
    def test_a_missing_header_is_named(self, sample_events):
        assert _only_problem(sample_events[1:]) == (
            "line 1 (topology): the first line must be the header, "
            '{"type": "header", "schema_version": "1.0", "backend": ...}'
        )

    def test_only_the_first_line_may_be_a_header(self, sample_events):
        sample_events.insert(3, dict(sample_events[0]))
        assert _only_problem(sample_events) == (
            "line 4 (header): only the first line may be a header"
        )

    def test_a_newer_major_version_is_refused(self, sample_events):
        sample_events[0]["schema_version"] = "2.0"
        assert _only_problem(sample_events) == (
            'line 1 (header): schema_version "2.0" is not supported; '
            "this package reads 1.x recordings"
        )

    def test_a_newer_minor_version_is_read(self, sample_events):
        sample_events[0]["schema_version"] = "1.3"
        report = validate_events(sample_events)
        assert report.ok
        assert report.schema_version == "1.3"

    def test_schema_version_is_required(self, sample_events):
        del sample_events[0]["schema_version"]
        assert _only_problem(sample_events) == "line 1 (header): 'schema_version' is required"

    def test_backend_must_be_sim_or_live(self, sample_events):
        sample_events[0]["backend"] = "mininet"
        assert _only_problem(sample_events) == (
            "line 1 (header): 'backend' must be one of sim, live; got \"mininet\""
        )

    def test_seed_must_be_an_integer(self, sample_events):
        sample_events[0]["seed"] = "7"
        assert _only_problem(sample_events) == (
            "line 1 (header): 'seed' must be an integer or null, got \"7\""
        )

    def test_seed_may_be_absent_for_a_live_run(self, sample_events):
        del sample_events[0]["seed"]
        sample_events[0]["backend"] = "live"
        assert validate_events(sample_events).ok


class TestTopology:
    def test_a_recording_needs_one(self, sample_events):
        del sample_events[1]
        problems = _problems(sample_events)
        # Every server reference is unknown too, but those are not checked
        # without a roster: one clear cause beats ten echoes of it.
        assert problems == [
            "line 11: the recording has no topology event; one must follow the header, "
            "carrying the roster and the ground truth"
        ]

    def test_it_must_come_right_after_the_header(self, sample_events):
        topology = sample_events.pop(1)
        topology["ts"] = 121.0  # keep time order, so only the placement is wrong
        sample_events.insert(3, topology)
        assert _only_problem(sample_events) == (
            "line 4 (topology): the topology must come right after the header, before any "
            "event that refers to its nodes; 2 event(s) came first"
        )

    def test_a_recording_holds_one_run(self, sample_events):
        sample_events.insert(5, dict(sample_events[1], ts=121.4))
        assert _only_problem(sample_events) == (
            "line 6 (topology): a recording holds one run, so one topology; the first is on line 2"
        )

    def test_an_attacker_needs_its_onset(self, sample_events):
        del _node(sample_events, "srv3")["attack_start_s"]
        assert _only_problem(sample_events) == (
            "line 2 (topology): 'graph.nodes[2].attack_start_s' is required: \"srv3\" "
            'attacks ("on_off"), and detection latency is measured from its onset'
        )

    def test_an_honest_node_needs_no_onset(self, sample_events):
        assert "attack_start_s" not in _node(sample_events, "srv1")
        assert validate_events(sample_events).ok

    @pytest.mark.parametrize("node_id, index, kind", [("srv2", 1, "server"), ("iot1", 4, "iot")])
    def test_servers_and_clients_carry_ground_truth(self, sample_events, node_id, index, kind):
        del _node(sample_events, node_id)["attack"]
        assert _only_problem(sample_events) == (
            f"line 2 (topology): 'graph.nodes[{index}].attack' is required on a {kind} "
            'node; use "none" for an honest one'
        )

    def test_switches_carry_no_ground_truth(self, sample_events):
        sample_events[1]["graph"]["nodes"].append({"id": "s0", "kind": "core_switch"})
        assert validate_events(sample_events).ok

    def test_onset_must_not_be_negative(self, sample_events):
        _node(sample_events, "srv3")["attack_start_s"] = -5
        assert _only_problem(sample_events) == (
            "line 2 (topology): 'graph.nodes[2].attack_start_s' must be a non-negative "
            "number, got -5"
        )

    def test_node_ids_are_unique(self, sample_events):
        _node(sample_events, "srv4")["id"] = "srv1"
        assert _only_problem(sample_events) == (
            "line 2 (topology): 'graph.nodes[3].id' \"srv1\" is used by an earlier node"
        )

    def test_it_needs_a_server(self, sample_events):
        nodes = sample_events[1]["graph"]["nodes"]
        sample_events[1]["graph"]["nodes"] = [n for n in nodes if n["kind"] != "server"]
        problems = _problems(sample_events[:2])
        assert problems == ["line 2 (topology): the topology has no node of kind 'server'"]

    def test_nodes_must_be_a_non_empty_array(self, sample_events):
        sample_events[1]["graph"]["nodes"] = []
        problems = _problems(sample_events[:2])
        assert problems == ["line 2 (topology): 'graph.nodes' must be a non-empty array, got []"]

    def test_graph_is_required(self, sample_events):
        del sample_events[1]["graph"]
        assert _problems(sample_events[:2]) == ["line 2 (topology): 'graph' is required"]


class TestTimestamps:
    @pytest.mark.parametrize(
        "ts, shown",
        [(-1.0, "-1.0"), ("12", '"12"'), (True, "true"), (math.nan, "NaN"), (None, "null")],
    )
    def test_ts_must_be_a_non_negative_number(self, sample_events, ts, shown):
        sample_events[4]["ts"] = ts
        assert _only_problem(sample_events) == (
            f"line 5 (route): 'ts' must be a non-negative number, got {shown}"
        )

    def test_ts_is_required(self, sample_events):
        del sample_events[4]["ts"]
        assert _only_problem(sample_events) == "line 5 (route): 'ts' is required"

    def test_time_must_not_go_back(self, sample_events):
        sample_events[4]["ts"] = 100.0
        assert _only_problem(sample_events) == (
            "line 5 (route): ts 100.0 is earlier than 120.9 on line 4; "
            "events must be appended in time order"
        )

    def test_equal_timestamps_are_in_order(self, sample_events):
        # One poll's anomaly and node_status share a ts in real recordings.
        assert sample_events[7]["ts"] == sample_events[8]["ts"]
        assert validate_events(sample_events).ok


class TestEventFields:
    @pytest.mark.parametrize(
        "index, change, expected",
        [
            (
                2,
                {"chosen": "srv9"},
                "'chosen' names \"srv9\", which is not a server in the topology",
            ),
            (
                2,
                {"chosen": "iot1"},
                "'chosen' names \"iot1\", which is not a server in the topology",
            ),
            (2, {"chosen": ""}, "'chosen' must be a non-empty string, got \"\""),
            (3, {"latency_ms": -2}, "'latency_ms' must be a non-negative number, got -2"),
            (3, {"status": "ok"}, "'status' must be one of success, timeout, failure; got \"ok\""),
            (3, {"charged": "no"}, "'charged' must be true or false, got \"no\""),
            (3, {"task": 1.5}, "'task' must be an integer, got 1.5"),
            (7, {"signals": [0.4]}, "'signals' must be an object, got [0.4]"),
            (
                7,
                {"signals": {"packet_drop": "high"}},
                "'signals.packet_drop' must be a finite number, got \"high\"",
            ),
            (9, {"kind": "server"}, "'kind' must be one of node, client; got \"server\""),
            (10, {"node": "srv7"}, "'node' names \"srv7\", which is not a server in the topology"),
        ],
    )
    def test_a_bad_field_is_named(self, sample_events, index, change, expected):
        sample_events[index].update(change)
        etype = sample_events[index]["type"]
        assert _only_problem(sample_events) == f"line {index + 1} ({etype}): {expected}"

    @pytest.mark.parametrize(
        "index, field",
        [
            (2, "chosen"),
            (3, "node"),
            (3, "status"),
            (3, "latency_ms"),
            (7, "signals"),
            (8, "nodes"),
            (9, "subject"),
            (9, "attack_type"),
            (10, "node"),
            (11, "reason"),
        ],
    )
    def test_a_missing_field_is_named(self, sample_events, index, field):
        del sample_events[index][field]
        etype = sample_events[index]["type"]
        assert _only_problem(sample_events) == f"line {index + 1} ({etype}): '{field}' is required"

    def test_a_classifier_may_withdraw_its_label(self, sample_events):
        sample_events[9]["attack_type"] = None
        assert validate_events(sample_events).ok

    def test_extra_fields_are_allowed(self, sample_events):
        sample_events[2]["ranked"] = [["srv1", 0.81], ["srv3", 0.79]]
        sample_events[2]["seq"] = 3
        assert validate_events(sample_events).ok

    def test_unknown_event_types_are_allowed(self, sample_events):
        # A live run records switch_up, flow_install, block and more; the
        # scorers skip what they do not read.
        sample_events.append({"type": "switch_up", "ts": 140.0, "dpid": 1})
        assert validate_events(sample_events).ok

    def test_unknown_event_types_still_need_a_ts(self, sample_events):
        sample_events.append({"type": "switch_up", "dpid": 1})
        assert _only_problem(sample_events) == "line 13 (switch_up): 'ts' is required"

    def test_type_must_be_a_string(self, sample_events):
        sample_events.append({"type": 3, "ts": 140.0})
        assert _only_problem(sample_events) == "line 13: 'type' must be a non-empty string, got 3"

    def test_a_line_must_be_an_object(self, sample_events):
        sample_events.append([1, 2])
        assert _only_problem(sample_events) == "line 13: expected a JSON object, got [1, 2]"

    def test_live_counters_are_checked_when_present(self, sample_events):
        sample_events.append({"type": "flow_stats", "ts": 140.0, "dpid": 2, "rules": []})
        assert validate_events(sample_events).ok
        sample_events.append({"type": "port_stats", "ts": 140.0, "dpid": "s1", "ports": []})
        assert _only_problem(sample_events) == (
            "line 14 (port_stats): 'dpid' must be an integer, got \"s1\""
        )


class TestFile:
    def _check(self, tmp_path, text):
        path = tmp_path / "run.jsonl"
        path.write_text(text, encoding="utf-8")
        return [str(p) for p in validate_file(path).problems]

    def _sample_text(self, sample_path):
        return sample_path.read_text("utf-8")

    def test_a_blank_line_is_a_problem(self, tmp_path, sample_path):
        lines = self._sample_text(sample_path).splitlines(keepends=True)
        lines.insert(3, "\n")
        assert self._check(tmp_path, "".join(lines)) == [
            "line 4: blank line; every line must hold one JSON object"
        ]

    def test_nan_tokens_are_not_json(self, tmp_path, sample_path):
        text = self._sample_text(sample_path).replace('"edge_score": 0.81', '"edge_score": NaN')
        assert self._check(tmp_path, text) == ["line 3: not valid JSON: NaN is not a JSON number"]

    def test_an_empty_file(self, tmp_path):
        assert self._check(tmp_path, "") == [
            "line 1: the recording is empty; it needs a header and a topology"
        ]

    def test_windows_line_endings_are_fine(self, tmp_path, sample_path):
        text = self._sample_text(sample_path).replace("\n", "\r\n")
        path = tmp_path / "run.jsonl"
        path.write_bytes(text.encode("utf-8"))
        assert validate_file(path).ok

    def test_line_count_includes_broken_lines(self, broken_path):
        assert validate_file(broken_path).lines == 6


class TestReport:
    def test_lists_a_limited_number_of_problems(self):
        problems = tuple(Problem(i, "bad", "route") for i in range(1, 6))
        text = Report(problems, 5, "1.0").format("run.jsonl", max_problems=2)
        assert text.splitlines() == [
            "run.jsonl: 5 problems",
            "  line 1 (route): bad",
            "  line 2 (route): bad",
            "  ... and 3 more",
        ]

    def test_one_problem_is_singular(self):
        text = Report((Problem(1, "bad"),), 1, None).format("run.jsonl")
        assert text.splitlines()[0] == "run.jsonl: 1 problem"


class TestCommandLine:
    def test_valid_file_exits_zero(self, sample_path, capsys):
        assert main([str(sample_path)]) == 0
        assert capsys.readouterr().out.strip().endswith("valid, schema 1.0, 12 lines")

    def test_broken_file_exits_one(self, sample_path, broken_path, capsys):
        assert main([str(sample_path), str(broken_path), "--max-problems", "1"]) == 1
        out = capsys.readouterr().out.splitlines()
        assert out[1].endswith("broken_run.jsonl: 5 problems")
        assert out[3] == "  ... and 4 more"

    def test_unreadable_file_exits_two(self, tmp_path, capsys):
        assert main([str(tmp_path / "missing.jsonl")]) == 2
        assert "cannot read" in capsys.readouterr().out

    def test_runs_as_a_module(self, broken_path):
        result = subprocess.run(
            [sys.executable, "-m", "turncoat_sdn.events.validate", str(broken_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "line 3 (route)" in result.stdout
        assert result.stderr == ""


class TestScorersReadIt:
    def test_the_attack_scorer_finds_ground_truth_and_onset(self, sample_path):
        events = read_events(sample_path)
        assert ground_truth(events)["srv3"] == ("node", "on_off")
        assert ground_truth(events)["srv1"] == ("node", "none")
        assert onset_times(events) == {"srv3": 120.0}


class TestDocs:
    """docs/event-format.md describes every event type and field the schema declares."""

    def _documented(self):
        return set(re.findall(r"`([a-z_]+)`", DOC.read_text("utf-8")))

    def test_every_event_type_is_documented(self):
        types = {schema.HEADER, schema.TOPOLOGY, *schema.EVENT_FIELDS, *schema.LIVE_EVENT_FIELDS}
        assert types - self._documented() == set()

    def test_every_field_is_documented(self):
        groups = [
            schema.HEADER_FIELDS,
            schema.COMMON_FIELDS,
            schema.TOPOLOGY_FIELDS,
            schema.TOPOLOGY_NODE_FIELDS,
            *schema.EVENT_FIELDS.values(),
            *schema.LIVE_EVENT_FIELDS.values(),
        ]
        names = {f.name for group in groups for f in group}
        assert names - self._documented() == set()
