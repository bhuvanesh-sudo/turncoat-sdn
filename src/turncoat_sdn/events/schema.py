"""The ``events.jsonl`` schema, version 1.0, written down as data.

A recording is one JSON object per line, appended in time order:

1. a ``header`` line carrying ``schema_version`` and how the run was made,
2. a ``topology`` event with the roster and the ground truth (who attacks,
   and from when),
3. everything else, each event with a ``type`` and a ``ts`` in seconds since
   the run started.

The field tables below are what :mod:`turncoat_sdn.events.validate` checks and
what ``docs/event-format.md`` describes. Event shapes follow what the
final-year project's controller already recorded and what the scorers already
read, so existing recordings need a header and run-relative ``ts``, not a
rewrite. Fields not listed here are allowed and ignored, and so are event
types not listed here: producers may record more than the scorers need.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The version a writer stamps into every header. Readers accept any 1.x.
SCHEMA_VERSION = "1.0"

HEADER = "header"
TOPOLOGY = "topology"

#: ``header.backend``: where the recording came from.
BACKENDS = ("sim", "live")

#: ``report.status``: the outcome a client saw for one task.
REPORT_STATUSES = ("success", "timeout", "failure")

#: ``classification.kind``: whether the subject is a server or an IoT client.
SUBJECT_KINDS = ("node", "client")

#: Topology node kinds that carry ground truth (``attack``, ``attack_start_s``).
GROUND_TRUTH_KINDS = ("server", "iot")

#: The ``attack`` value of an honest node.
NO_ATTACK = "none"

# Value kinds a field can take.
STRING = "string"
NUMBER = "number"  # finite int or float, never a bool
NON_NEGATIVE = "non-negative number"
INTEGER = "integer"
BOOLEAN = "boolean"
OBJECT = "object"
ARRAY = "array"


@dataclass(frozen=True)
class Field:
    """One field of an event type.

    kind: one of the value kinds above.
    required: the field must be present.
    nullable: ``null`` is accepted as well as ``kind``.
    choices: the only strings accepted, when not empty.
    server_ref: the value must be the id of a server in the topology.
    """

    name: str
    kind: str
    required: bool = True
    nullable: bool = False
    choices: tuple[str, ...] = ()
    server_ref: bool = False


HEADER_FIELDS: tuple[Field, ...] = (
    Field("schema_version", STRING),
    Field("backend", STRING, choices=BACKENDS),
    Field("seed", INTEGER, required=False, nullable=True),
    Field("strategy", STRING, required=False),
    Field("scenario", STRING, required=False),
)

#: The fields every event after the header carries.
COMMON_FIELDS: tuple[Field, ...] = (
    Field("type", STRING),
    Field("ts", NON_NEGATIVE),
)

#: Fields of the topology's ``graph`` object, and of each node in it. Checked
#: by hand in the validator because they are nested.
TOPOLOGY_FIELDS: tuple[Field, ...] = (Field("graph", OBJECT),)
TOPOLOGY_NODE_FIELDS: tuple[Field, ...] = (
    Field("id", STRING),
    Field("kind", STRING),
    Field("attack", STRING, required=False),
    Field("attack_start_s", NON_NEGATIVE, required=False),
    Field("ip", STRING, required=False),
)

#: Event types the scorers read, and the fields each one must carry.
EVENT_FIELDS: dict[str, tuple[Field, ...]] = {
    "route": (
        Field("chosen", STRING, server_ref=True),
        Field("task", INTEGER, required=False),
        Field("client_ip", STRING, required=False),
        Field("edge_score", NUMBER, required=False, nullable=True),
        Field("decision_ms", NON_NEGATIVE, required=False),
    ),
    "route_denied": (
        Field("reason", STRING),
        Field("client_ip", STRING, required=False),
    ),
    "report": (
        Field("node", STRING, server_ref=True),
        Field("status", STRING, choices=REPORT_STATUSES),
        Field("latency_ms", NON_NEGATIVE),
        Field("task", INTEGER, required=False),
        Field("device", STRING, required=False),
        Field("charged", BOOLEAN, required=False),
    ),
    "anomaly": (
        Field("node", STRING, server_ref=True),
        Field("signals", OBJECT),
        Field("reasons", ARRAY, required=False),
        Field("anomaly", NUMBER, required=False),
    ),
    "node_status": (Field("nodes", OBJECT),),
    "classification": (
        Field("subject", STRING),
        Field("kind", STRING, choices=SUBJECT_KINDS),
        Field("attack_type", STRING, nullable=True),
        Field("confidence", NUMBER, required=False),
    ),
    "quarantine": (
        Field("node", STRING, server_ref=True),
        Field("trust", NUMBER, required=False),
        Field("anomaly", NUMBER, required=False),
    ),
    "recovered": (
        Field("node", STRING, server_ref=True),
        Field("trust", NUMBER, required=False),
        Field("anomaly", NUMBER, required=False),
    ),
    "reroute": (
        Field("from_node", STRING, server_ref=True),
        Field("to_node", STRING, server_ref=True),
        Field("client_ip", STRING, required=False),
    ),
    "flood": (
        Field("client_ip", STRING),
        Field("ratio", NUMBER, required=False, nullable=True),
        Field("rate_hz", NON_NEGATIVE, required=False),
    ),
    "auth_denied": (
        Field("device_id", STRING),
        Field("source_ip", STRING, required=False),
        Field("kind", STRING, required=False, nullable=True),
    ),
}

#: Data-plane counters only a live backend produces. Whether these stay in the
#: core schema or become a live-only extension is open until the v0.2
#: kickoff decides; until then they are checked when present, never required.
LIVE_EVENT_FIELDS: dict[str, tuple[Field, ...]] = {
    "flow_stats": (
        Field("dpid", INTEGER),
        Field("rules", ARRAY),
    ),
    "port_stats": (
        Field("dpid", INTEGER),
        Field("ports", ARRAY),
    ),
}


def supported_version(version: str) -> bool:
    """Whether a recording's ``schema_version`` can be read by this package.

    Minor versions only add optional fields and event types, so any 1.x reads.
    """
    major, _, _ = version.partition(".")
    return major == SCHEMA_VERSION.partition(".")[0]
