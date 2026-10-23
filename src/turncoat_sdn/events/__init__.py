"""The shared ``events.jsonl`` format: schema, JSONL writer and reader, validator.

Owner: arj (Event format and live recording track).
Lands in: v0.2.
Ported from the final-year project:
controller/event_bus.py (JSONL part), evaluation/nfr_report.load_events.

Everything that produces runs writes this format, and everything that grades
runs reads it. A recording opens with a ``header`` line (``schema_version``,
backend, seed, strategy, scenario), then one ``topology`` event with the
roster and ground truth, then the run's events in time order::

    from turncoat_sdn.events import EventWriter, read_events
    from turncoat_sdn.events.validate import validate_file

    with EventWriter("run.jsonl", backend="sim", seed=7) as rec:
        rec.write("topology", 0.0, graph={"nodes": [...], "links": []})
        ...

    report = validate_file("run.jsonl")
    print(report.format("run.jsonl"))
    events = read_events("run.jsonl")

The schema itself is in :mod:`turncoat_sdn.events.schema` and described in
docs/event-format.md. The validator is imported from its own module rather
than re-exported, so ``python -m turncoat_sdn.events.validate`` runs cleanly.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from turncoat_sdn.events.jsonl import Event, EventWriter, read_events
from turncoat_sdn.events.schema import SCHEMA_VERSION, supported_version

__all__ = [
    "SCHEMA_VERSION",
    "Event",
    "EventWriter",
    "read_events",
    "supported_version",
]
