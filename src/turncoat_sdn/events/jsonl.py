"""Write and read ``events.jsonl`` recordings.

Ported from the final-year project: the JSONL recording half of
``controller/event_bus.py`` (the pub/sub fan-out to the dashboard stays
behind) and ``evaluation/nfr_report.load_events``.

Two changes from the original, both for the shared format:

* The writer starts every file with the ``header`` line, so a recording says
  which schema version it follows and how it was made.
* The caller passes ``ts``. The controller stamped wall-clock time; a
  recording now carries seconds since the run started, which the simulator
  knows and a live backend can compute.

Writing a recording::

    from turncoat_sdn.events import EventWriter

    with EventWriter("run.jsonl", backend="sim", seed=7, strategy="zt_sdn") as rec:
        rec.write("topology", 0.0, graph={"nodes": [...], "links": []})
        rec.write("route", 121.4, chosen="srv3", task=5812)

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from turncoat_sdn.events.schema import HEADER, SCHEMA_VERSION

Event = dict[str, Any]


class EventWriter:
    """Append events to a JSONL recording, one object per line.

    The file is line-buffered, so a run killed with Ctrl-C still leaves a
    complete, readable file up to its last event. Writes are serialised by a
    lock, so a live backend can record from several threads.

    Values must be JSON-safe. ``NaN`` and infinities raise ``ValueError``
    instead of being written as tokens that strict JSON parsers reject.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        backend: str,
        seed: int | None = None,
        strategy: str | None = None,
        scenario: str | None = None,
        **header_fields: Any,
    ) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO | None = open(self.path, "w", encoding="utf-8", buffering=1)

        header: Event = {"type": HEADER, "schema_version": SCHEMA_VERSION, "backend": backend}
        for key, value in (("seed", seed), ("strategy", strategy), ("scenario", scenario)):
            if value is not None:
                header[key] = value
        header.update(header_fields)
        self.header = header
        self._write_line(header)

    def write(self, event_type: str, ts: float, **fields: Any) -> Event:
        """Record one event and return it as written.

        ``ts`` is seconds since the run started. Events must be written in
        time order; the validator rejects a recording whose ``ts`` goes back.
        """
        if "type" in fields:
            raise ValueError("pass the event type as event_type, not as a field")
        event: Event = {"type": event_type, "ts": ts, **fields}
        self._write_line(event)
        return event

    def _write_line(self, event: Event) -> None:
        line = json.dumps(event, allow_nan=False) + "\n"
        with self._lock:
            if self._file is None:
                raise ValueError(f"the recording {self.path} is already closed")
            self._file.write(line)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def __enter__(self) -> EventWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class EventList:
    """Keep a recording in memory, exactly as :func:`read_events` would return it.

    It takes the same arguments as :class:`EventWriter`, minus the path, and
    fills :attr:`events` with the header and every event written. Each event is
    passed through JSON on the way in, so it holds what a file would hold: the
    same values, lists for tuples, and ``ValueError`` for ``NaN``. Scoring many
    runs this way skips writing and parsing a file per run.
    """

    def __init__(
        self,
        *,
        backend: str,
        seed: int | None = None,
        strategy: str | None = None,
        scenario: str | None = None,
        **header_fields: Any,
    ) -> None:
        header: Event = {"type": HEADER, "schema_version": SCHEMA_VERSION, "backend": backend}
        for key, value in (("seed", seed), ("strategy", strategy), ("scenario", scenario)):
            if value is not None:
                header[key] = value
        header.update(header_fields)
        self.header = header
        self.events: list[Event] = []
        self._append(header)

    def write(self, event_type: str, ts: float, **fields: Any) -> Event:
        """Record one event and return it as stored, as :meth:`EventWriter.write` does."""
        if "type" in fields:
            raise ValueError("pass the event type as event_type, not as a field")
        return self._append({"type": event_type, "ts": ts, **fields})

    def _append(self, event: Event) -> Event:
        stored: Event = json.loads(json.dumps(event, allow_nan=False))
        self.events.append(stored)
        return stored


def read_events(path: str | os.PathLike[str]) -> list[Event]:
    """Parse a JSONL recording, header line included.

    Skips blank and malformed lines rather than failing on one truncated tail
    line, which a run killed mid-write can leave. This is the lenient path the
    scorers use; run :func:`turncoat_sdn.events.validate.validate_file` to find out
    whether a recording is actually well formed.
    """
    events: list[Event] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events
