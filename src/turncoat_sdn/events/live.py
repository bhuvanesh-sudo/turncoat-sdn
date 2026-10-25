"""Convert a live recording from the final-year controller to schema 1.0.

Owner: arj (Event format and live recording track).
Lands in: v1.0.
Ported from the final-year project: the recording half of
``controller/event_bus.py``, which wrote ``data/events.jsonl`` on every live
run.

In the final-year project, the IoT clients write no file of their own. Each
``iot_client`` POSTs its task outcome to the controller's northbound API, and
the controller publishes it as a ``report`` on its event bus, beside every
``route``, ``anomaly`` and ``quarantine``. A live run therefore leaves one
recording, and it differs from schema 1.0 in four ways:

* it has no ``header`` line;
* ``ts`` is wall-clock time (``time.time()``), not seconds since the run started;
* lines can be slightly out of time order, because the bus stamped ``ts``
  before taking its lock and wrote the line after releasing it;
* every event carries a ``seq`` counter for the dashboard's backfill.

:func:`convert_live_file` turns such a recording into schema 1.0, so it
scores with the same commands as a simulated run::

    from turncoat_sdn.events import convert_live_file

    conversion = convert_live_file("data/events.jsonl", "live.jsonl", strategy="zt_sdn")
    print("\\n".join(conversion.notes()))

``turncoat convert`` wraps the same call (see docs/cli.md). The live backend
in ``backends/mininet/`` needs none of this: it records schema 1.0 directly.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from turncoat_sdn.events.jsonl import Event, EventList, EventWriter
from turncoat_sdn.events.schema import HEADER, TOPOLOGY

#: ``header.backend`` of every recording this module writes.
LIVE_BACKEND = "live"

#: Decimal places kept on a converted ``ts``: microseconds, as the simulator writes.
TS_DECIMALS = 6

#: Fields the final-year event bus added that schema 1.0 does not keep.
DROPPED_FIELDS = ("seq",)


class ConversionError(ValueError):
    """A recording that cannot be converted, and why."""


@dataclass(frozen=True)
class Conversion:
    """A live recording converted to schema 1.0.

    events: the converted recording, header first, as
        :func:`turncoat_sdn.events.read_events` would return it.
    started_at: the wall-clock time ``ts`` now counts from, in Unix seconds.
    skipped_lines: blank or malformed lines left out, such as a tail line cut
        off when the controller was stopped mid-write.
    untimed: events left out because they had no numeric ``ts``.
    out_of_order: events that were stamped earlier than the line before them.
    non_finite: ``NaN`` or infinite values written as ``null``.
    """

    events: list[Event]
    started_at: float
    skipped_lines: int = 0
    untimed: int = 0
    out_of_order: int = 0
    non_finite: int = 0

    def notes(self) -> list[str]:
        """What the conversion changed, one line each, for a person to read."""
        out = [
            f"{len(self.events) - 1:,} events; ts now counts from the first stamp, "
            f"{self.started_at:.6f} (Unix time)"
        ]
        if self.out_of_order:
            out.append(f"{self.out_of_order:,} event(s) were out of time order and were moved")
        if self.skipped_lines:
            out.append(f"{self.skipped_lines:,} blank or malformed line(s) were left out")
        if self.untimed:
            out.append(f"{self.untimed:,} event(s) with no numeric ts were left out")
        if self.non_finite:
            out.append(f"{self.non_finite:,} NaN or infinite value(s) were written as null")
        return out


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite(value: Any, count: list[int]) -> Any:
    """``value`` with every NaN and infinity replaced by None, counted in ``count``."""
    if isinstance(value, float) and not math.isfinite(value):
        count[0] += 1
        return None
    if isinstance(value, dict):
        return {k: _finite(v, count) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v, count) for v in value]
    return value


def read_live_recording(path: str | os.PathLike[str]) -> tuple[list[Any], int]:
    """Parse a live recording leniently: the events, and how many lines were skipped.

    Unlike :func:`turncoat_sdn.events.read_events` it counts what it skips,
    and it accepts ``NaN`` and ``Infinity`` tokens, which the final-year bus
    could write, so that :func:`convert_live_events` can null them out.
    """
    events: list[Any] = []
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                skipped += 1
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
    return events, skipped


def convert_live_events(
    raw: Iterable[Any],
    *,
    seed: int | None = None,
    strategy: str | None = None,
    scenario: str | None = None,
    skipped_lines: int = 0,
) -> Conversion:
    """Convert events recorded by the final-year controller to schema 1.0.

    The recording must hold exactly one ``topology`` event, the roster and
    ground truth the controller publishes once at start-up. ``ts`` is moved to
    count from the earliest stamp in the file, rounded to microseconds, and the
    topology is placed first at ``ts`` 0. Every other event is put in time
    order, keeping file order between equal stamps, and loses its ``seq``. All
    other fields are kept as they are.

    ``seed``, ``strategy`` and ``scenario`` go into the header, because the
    recording itself does not say how the run was made.

    Raises :class:`ConversionError` for a recording that already has a header,
    has no topology, or holds more than one run.
    """
    timed: list[tuple[float, int, dict[str, Any]]] = []
    topology: dict[str, Any] | None = None
    topologies = untimed = out_of_order = 0
    non_finite = [0]
    last_ts: float | None = None

    for index, event in enumerate(raw):
        if not isinstance(event, dict):
            skipped_lines += 1
            continue
        if event.get("type") == HEADER:
            raise ConversionError(
                "the recording already starts with a header, so it is in the shared "
                "format; check it with turncoat validate instead"
            )
        ts = event.get("ts")
        if not _is_number(ts):
            untimed += 1
            continue
        if last_ts is not None and ts < last_ts:
            out_of_order += 1
        else:
            last_ts = ts
        clean = {
            k: _finite(v, non_finite)
            for k, v in event.items()
            if k not in DROPPED_FIELDS and k not in ("type", "ts")
        }
        etype = event.get("type")
        if etype == TOPOLOGY:
            topologies += 1
            topology = clean
        timed.append((float(ts), index, {"type": etype, **clean}))

    if topology is None:
        raise ConversionError(
            "the recording has no topology event, so it carries no roster and no ground "
            "truth; the controller publishes one at start-up, so the start of the run is missing"
        )
    if topologies > 1:
        raise ConversionError(
            f"the recording holds {topologies} topology events, one per controller start; "
            "a recording holds one run, so split it at each topology and convert each part"
        )

    started_at = min(ts for ts, _, _ in timed)
    recording = EventList(
        backend=LIVE_BACKEND,
        seed=seed,
        strategy=strategy,
        scenario=scenario,
        started_at=started_at,
    )
    recording.write(TOPOLOGY, 0.0, **topology)
    for ts, _, event in sorted(timed, key=lambda item: (item[0], item[1])):
        if event["type"] == TOPOLOGY:
            continue
        fields = {k: v for k, v in event.items() if k != "type"}
        recording.write(event["type"], round(ts - started_at, TS_DECIMALS), **fields)

    return Conversion(
        events=recording.events,
        started_at=started_at,
        skipped_lines=skipped_lines,
        untimed=untimed,
        out_of_order=out_of_order,
        non_finite=non_finite[0],
    )


def write_recording(events: Iterable[Event], path: str | os.PathLike[str]) -> None:
    """Write a recording held in memory, header first, with :class:`EventWriter`."""
    it = iter(events)
    header = dict(next(it))
    if header.pop("type", None) != HEADER:
        raise ValueError("a recording starts with its header")
    header.pop("schema_version", None)
    backend = header.pop("backend")
    with EventWriter(path, backend=backend, **header) as rec:
        for event in it:
            fields = {k: v for k, v in event.items() if k not in ("type", "ts")}
            rec.write(event["type"], event["ts"], **fields)


def convert_live_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    seed: int | None = None,
    strategy: str | None = None,
    scenario: str | None = None,
) -> Conversion:
    """Convert the live recording at ``source`` and write it to ``target``.

    See :func:`convert_live_events` for what changes. Nothing is written when
    the conversion is refused.
    """
    raw, skipped = read_live_recording(source)
    conversion = convert_live_events(
        raw, seed=seed, strategy=strategy, scenario=scenario, skipped_lines=skipped
    )
    write_recording(conversion.events, target)
    return conversion
