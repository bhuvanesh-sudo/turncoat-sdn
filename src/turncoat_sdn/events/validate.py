"""Check that a recording follows the ``events.jsonl`` schema.

The reader is lenient on purpose: a scorer should still grade a run whose last
line was cut off. The validator is strict, so that whoever produces
recordings (the simulator, a live testbed, someone else's system) can find out
exactly what is wrong before a scorer quietly works around it. Every problem
names the line it is on::

    broken.jsonl: 2 problems
      line 4 (route): 'chosen' names 'srv9', which is not a server in the topology
      line 6 (report): 'status' must be one of success, timeout, failure; got "ok"

From Python::

    from turncoat_sdn.events.validate import validate_file

    report = validate_file("run.jsonl")
    print(report.format("run.jsonl"))

From a shell, until ``turncoat validate`` lands::

    python -m turncoat_sdn.events.validate run.jsonl

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from turncoat_sdn.events.schema import (
    ARRAY,
    BOOLEAN,
    COMMON_FIELDS,
    EVENT_FIELDS,
    GROUND_TRUTH_KINDS,
    HEADER,
    HEADER_FIELDS,
    INTEGER,
    LIVE_EVENT_FIELDS,
    NO_ATTACK,
    NON_NEGATIVE,
    NUMBER,
    OBJECT,
    SCHEMA_VERSION,
    STRING,
    TOPOLOGY,
    TOPOLOGY_FIELDS,
    TOPOLOGY_NODE_FIELDS,
    Field,
    supported_version,
)

#: How many problems :meth:`Report.format` lists before summarising the rest.
DEFAULT_MAX_PROBLEMS = 20

_KNOWN_FIELDS = {**EVENT_FIELDS, **LIVE_EVENT_FIELDS}


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a recording, and the line it is on."""

    line: int
    message: str
    event_type: str | None = None

    def __str__(self) -> str:
        where = f"line {self.line}"
        if self.event_type:
            where += f" ({self.event_type})"
        return f"{where}: {self.message}"


@dataclass(frozen=True)
class Report:
    """The outcome of validating one recording.

    lines: how many lines were checked, the header included.
    schema_version: the version the header declares, or None without a header.
    """

    problems: tuple[Problem, ...]
    lines: int
    schema_version: str | None

    @property
    def ok(self) -> bool:
        return not self.problems

    def format(self, name: str, max_problems: int = DEFAULT_MAX_PROBLEMS) -> str:
        """A human-readable verdict, listing at most ``max_problems`` problems."""
        if self.ok:
            return f"{name}: valid, schema {self.schema_version}, {self.lines} lines"
        count = len(self.problems)
        out = [f"{name}: {count} problem{'s' if count != 1 else ''}"]
        out += [f"  {p}" for p in self.problems[:max_problems]]
        if count > max_problems:
            out.append(f"  ... and {count - max_problems} more")
        return "\n".join(out)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_KIND_CHECKS = {
    STRING: lambda v: isinstance(v, str) and v != "",
    NUMBER: _is_number,
    NON_NEGATIVE: lambda v: _is_number(v) and v >= 0,
    INTEGER: lambda v: isinstance(v, int) and not isinstance(v, bool),
    BOOLEAN: lambda v: isinstance(v, bool),
    OBJECT: lambda v: isinstance(v, dict),
    ARRAY: lambda v: isinstance(v, list),
}

_KIND_NAMES = {
    STRING: "a non-empty string",
    NUMBER: "a finite number",
    NON_NEGATIVE: "a non-negative number",
    INTEGER: "an integer",
    BOOLEAN: "true or false",
    OBJECT: "an object",
    ARRAY: "an array",
}


def _show(value: Any) -> str:
    """A short JSON rendering of a bad value, for a message."""
    text = json.dumps(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _check_fields(
    fields: Iterable[Field],
    obj: Mapping[str, Any],
    servers: frozenset[str] | None,
    prefix: str = "",
) -> list[str]:
    """Messages for every field of ``obj`` that breaks its declaration.

    ``servers`` is None when the topology is not known yet, which skips the
    server-reference checks rather than flagging every one of them.
    """
    messages = []
    for field in fields:
        path = f"'{prefix}{field.name}'"
        if field.name not in obj:
            if field.required:
                messages.append(f"{path} is required")
            continue
        value = obj[field.name]
        if value is None and field.nullable:
            continue
        if not _KIND_CHECKS[field.kind](value):
            nullable = " or null" if field.nullable else ""
            messages.append(
                f"{path} must be {_KIND_NAMES[field.kind]}{nullable}, got {_show(value)}"
            )
            continue
        if field.choices and value not in field.choices:
            messages.append(f"{path} must be one of {', '.join(field.choices)}; got {_show(value)}")
        elif field.server_ref and servers is not None and value not in servers:
            messages.append(f"{path} names {_show(value)}, which is not a server in the topology")
    return messages


class _Checker:
    """Checks events one at a time, carrying what earlier lines established."""

    def __init__(self) -> None:
        self.problems: list[Problem] = []
        self.lines = 0
        self.schema_version: str | None = None
        self.servers: frozenset[str] | None = None
        self.topology_line: int | None = None
        self.events_before_topology = 0
        self.last_ts: float | None = None
        self.last_ts_line = 0

    def add(self, line: int, message: str, event_type: str | None = None) -> None:
        self.problems.append(Problem(line, message, event_type))

    def check(self, line: int, event: Any) -> None:
        first = self.lines == 0
        self.lines += 1
        if not isinstance(event, dict):
            self.add(line, f"expected a JSON object, got {_show(event)}")
            return

        etype = event.get("type")
        label = etype if isinstance(etype, str) and etype else None

        if first:
            if etype == HEADER:
                self._check_header(line, event)
                return
            self.add(
                line,
                "the first line must be the header, "
                f'{{"type": "header", "schema_version": "{SCHEMA_VERSION}", "backend": ...}}',
                label,
            )
        elif etype == HEADER:
            self.add(line, "only the first line may be a header", HEADER)
            return

        for message in _check_fields(COMMON_FIELDS, event, None):
            self.add(line, message, label)
        self._check_order(line, event.get("ts"), label)
        if label is None:
            return

        if label == TOPOLOGY:
            self._check_topology(line, event)
        else:
            if self.topology_line is None:
                self.events_before_topology += 1
            fields = _KNOWN_FIELDS.get(label, ())
            for message in _check_fields(fields, event, self.servers):
                self.add(line, message, label)
            if label == "anomaly" and isinstance(event.get("signals"), dict):
                for name, value in event["signals"].items():
                    if not _is_number(value):
                        self.add(
                            line,
                            f"'signals.{name}' must be a finite number, got {_show(value)}",
                            label,
                        )

    def _check_header(self, line: int, event: Mapping[str, Any]) -> None:
        for message in _check_fields(HEADER_FIELDS, event, None):
            self.add(line, message, HEADER)
        version = event.get("schema_version")
        if isinstance(version, str) and version:
            self.schema_version = version
            if not supported_version(version):
                major = SCHEMA_VERSION.partition(".")[0]
                self.add(
                    line,
                    f"schema_version {_show(version)} is not supported; "
                    f"this package reads {major}.x recordings",
                    HEADER,
                )

    def _check_order(self, line: int, ts: Any, label: str | None) -> None:
        if not _is_number(ts) or ts < 0:
            return
        if self.last_ts is not None and ts < self.last_ts:
            self.add(
                line,
                f"ts {ts} is earlier than {self.last_ts} on line {self.last_ts_line}; "
                "events must be appended in time order",
                label,
            )
            return
        self.last_ts = ts
        self.last_ts_line = line

    def _check_topology(self, line: int, event: Mapping[str, Any]) -> None:
        if self.topology_line is not None:
            self.add(
                line,
                f"a recording holds one run, so one topology; the first is on line "
                f"{self.topology_line}",
                TOPOLOGY,
            )
            return
        self.topology_line = line
        if self.events_before_topology:
            self.add(
                line,
                "the topology must come right after the header, before any event "
                f"that refers to its nodes; {self.events_before_topology} event(s) came first",
                TOPOLOGY,
            )

        messages = _check_fields(TOPOLOGY_FIELDS, event, None)
        graph = event.get("graph")
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if isinstance(graph, dict) and (not isinstance(nodes, list) or not nodes):
            messages.append(f"'graph.nodes' must be a non-empty array, got {_show(nodes)}")
        servers: set[str] = set()
        seen: set[str] = set()
        for i, node in enumerate(nodes if isinstance(nodes, list) else ()):
            messages += self._check_topology_node(i, node, seen, servers)
        if isinstance(nodes, list) and nodes and not servers:
            messages.append("the topology has no node of kind 'server'")
        for message in messages:
            self.add(line, message, TOPOLOGY)
        self.servers = frozenset(servers)

    @staticmethod
    def _check_topology_node(i: int, node: Any, seen: set[str], servers: set[str]) -> list[str]:
        prefix = f"graph.nodes[{i}]."
        if not isinstance(node, dict):
            return [f"'graph.nodes[{i}]' must be an object, got {_show(node)}"]
        messages = _check_fields(TOPOLOGY_NODE_FIELDS, node, None, prefix)
        node_id, kind = node.get("id"), node.get("kind")
        if isinstance(node_id, str) and node_id:
            if node_id in seen:
                messages.append(f"'{prefix}id' {_show(node_id)} is used by an earlier node")
            seen.add(node_id)
            if kind == "server":
                servers.add(node_id)
        if kind in GROUND_TRUTH_KINDS:
            attack = node.get("attack")
            if "attack" not in node:
                messages.append(
                    f"'{prefix}attack' is required on a {kind} node; "
                    f'use "{NO_ATTACK}" for an honest one'
                )
            elif isinstance(attack, str) and attack != NO_ATTACK and "attack_start_s" not in node:
                messages.append(
                    f"'{prefix}attack_start_s' is required: {_show(node_id)} attacks "
                    f"({_show(attack)}), and detection latency is measured from its onset"
                )
        return messages

    def finish(self) -> Report:
        if self.lines == 0:
            self.add(1, "the recording is empty; it needs a header and a topology")
        elif self.topology_line is None:
            self.add(
                self.lines,
                "the recording has no topology event; one must follow the header, "
                "carrying the roster and the ground truth",
            )
        return Report(tuple(self.problems), self.lines, self.schema_version)


def validate_events(events: Iterable[Any]) -> Report:
    """Validate events already in memory, header first.

    Line numbers in the report count events from 1, as they would appear in a
    file written with :class:`turncoat_sdn.events.EventWriter`.
    """
    checker = _Checker()
    for line, event in enumerate(events, start=1):
        checker.check(line, event)
    return checker.finish()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def validate_file(path: str | os.PathLike[str]) -> Report:
    """Validate a JSONL recording on disk.

    Stricter than :func:`turncoat_sdn.events.read_events`: a blank line, a
    line that is not JSON (a truncated tail included) and ``NaN`` or
    ``Infinity`` tokens are all problems.
    """
    checker = _Checker()
    blank_or_broken = 0
    with open(path, encoding="utf-8") as f:
        for line, text in enumerate(f, start=1):
            if not text.strip():
                checker.add(line, "blank line; every line must hold one JSON object")
                blank_or_broken += 1
                continue
            try:
                event = json.loads(text.rstrip(), parse_constant=_reject_constant)
            except json.JSONDecodeError as exc:
                # "Unterminated string starting at" reads on into the column.
                reason = exc.msg.removesuffix(" at")
                checker.add(line, f"not valid JSON: {reason} at column {exc.colno}")
                blank_or_broken += 1
                continue
            except ValueError as exc:
                checker.add(line, f"not valid JSON: {exc}")
                blank_or_broken += 1
                continue
            checker.check(line, event)
    report = checker.finish()
    return Report(report.problems, report.lines + blank_or_broken, report.schema_version)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate recordings; exit 0 when all are valid, 1 when any is not, 2 when unreadable."""
    parser = argparse.ArgumentParser(
        prog="python -m turncoat_sdn.events.validate",
        description="Check that events.jsonl recordings follow the turncoat-sdn schema.",
    )
    parser.add_argument("paths", nargs="+", help="one or more JSONL recordings")
    parser.add_argument(
        "--max-problems",
        type=int,
        default=DEFAULT_MAX_PROBLEMS,
        help=f"problems to list per file (default {DEFAULT_MAX_PROBLEMS})",
    )
    args = parser.parse_args(argv)

    status = 0
    for path in args.paths:
        try:
            report = validate_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot read: {exc}")
            status = max(status, 2)
            continue
        print(report.format(path, args.max_problems))
        if not report.ok:
            status = max(status, 1)
    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
