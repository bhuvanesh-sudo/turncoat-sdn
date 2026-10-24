"""``turncoat score``: grade one recording.

Three questions, answered from the recording alone:

* **Who was caught?** The attack classifier replays the detector evidence and
  each subject's label is scored against the ground truth in ``topology``
  (:mod:`turncoat_sdn.scoring.attack_report`).
* **How fast?** Detection latency from that report, and the first
  ``quarantine`` of each attacker, measured from its onset. An IoT client is
  never quarantined; it is refused at admission, and ``auth_denied`` events
  count those refusals.
* **At what cost?** Service totals rebuilt from ``route``, ``route_denied``
  and ``report`` events, then passed to the NFR and availability scorers.

The service totals count exactly what the simulator counts, so for a
simulated run they equal its :class:`~turncoat_sdn.sim.RunResult`. Any system
that writes the shared format can be scored the same way.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.events import Event, read_events
from turncoat_sdn.events.schema import HEADER, NO_ATTACK, TOPOLOGY
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring import score_availability, score_nfr
from turncoat_sdn.scoring.attack_report import (
    DEFAULT_WINDOW_CYCLES,
    SubjectResult,
    format_report,
    ground_truth,
    onset_times,
    score_run,
    subject_aliases,
)

#: The SLO deadline when the recording does not carry one, as in the simulator.
DEFAULT_SLO_MS = 500.0
#: Decimal places kept in ``--json`` output, so scores compare exactly across platforms.
JSON_DECIMALS = 6


def _header(events: Sequence[Event]) -> dict[str, Any]:
    for event in events:
        if event.get("type") == HEADER:
            return {k: v for k, v in event.items() if k != "type"}
    return {}


def recorded_slo_ms(events: Sequence[Event]) -> float:
    """The SLO deadline from the ``topology`` event's ``config``, if a simulator wrote one."""
    for event in events:
        if event.get("type") == TOPOLOGY:
            config = event.get("config")
            if isinstance(config, dict):
                slo = config.get("slo_ms")
                if isinstance(slo, (int, float)) and not isinstance(slo, bool) and slo > 0:
                    return float(slo)
            break
    return DEFAULT_SLO_MS


def service_totals(events: Sequence[Event], slo_ms: float) -> dict[str, Any]:
    """Rebuild the run's task counts from its routing and outcome events.

    A task is offered once, as a ``route`` or a ``route_denied``. A denial and
    any outcome other than ``success`` count as failed and as an SLO
    violation; a success counts as a violation when slower than ``slo_ms``.
    """
    offered = failed = completed = slo_violations = 0
    latencies: list[float] = []
    for event in events:
        kind = event.get("type")
        if kind == "route":
            offered += 1
        elif kind == "route_denied":
            offered += 1
            failed += 1
            slo_violations += 1
        elif kind == "report":
            if event.get("status") == "success":
                latency = float(event.get("latency_ms", 0.0))
                completed += 1
                latencies.append(latency)
                if latency > slo_ms:
                    slo_violations += 1
            else:
                failed += 1
                slo_violations += 1
    return {
        "offered": offered,
        "completed": completed,
        "failed": failed,
        "slo_violations": slo_violations,
        "latencies_ms": latencies,
    }


def attacker_share(events: Sequence[Event]) -> float | None:
    """Fraction of routed tasks sent to an attacking server after its onset.

    Traffic to a turncoat before it turns is traffic to an honest server, so
    it does not count, as in the simulator's ``malicious_share``. A server
    with no recorded onset counts from the start.
    """
    truth = ground_truth(events)
    onsets = onset_times(events)
    t0 = next((float(e["ts"]) for e in events if isinstance(e.get("ts"), (int, float))), 0.0)
    attackers = {
        s: t0 + onsets.get(s, 0.0)
        for s, (kind, label) in truth.items()
        if kind == "node" and label != NO_ATTACK
    }
    routed = to_attackers = 0
    for event in events:
        if event.get("type") == "route":
            routed += 1
            turned = attackers.get(event.get("chosen"))
            if turned is not None and float(event.get("ts", 0.0)) >= turned:
                to_attackers += 1
    if routed == 0:
        return None
    return to_attackers / routed


def first_quarantine(events: Sequence[Event]) -> dict[str, float]:
    """When each server was first quarantined, in seconds since the run started."""
    seen: dict[str, float] = {}
    for event in events:
        if event.get("type") == "quarantine":
            node = event.get("node")
            if isinstance(node, str) and node not in seen:
                seen[node] = float(event.get("ts", 0.0))
    return seen


def routed_after(events: Sequence[Event], node: str, since: float) -> int:
    """Tasks routed to ``node`` at or after ``since``.

    A ``quarantine`` event is the controller's verdict; whether traffic
    actually stops depends on the strategy. A trust-blind strategy keeps
    routing to a flagged server, and this count shows it.
    """
    count = 0
    for event in events:
        if event.get("type") == "route" and event.get("chosen") == node:
            if float(event.get("ts", 0.0)) >= since:
                count += 1
    return count


def refused_at_admission(events: Sequence[Event]) -> dict[str, int]:
    """How many requests the admission check refused from each sender.

    Keyed by the device that SENT the request, worked out from its source
    address, not by the identity it claimed: a spoofer's refusals are its own,
    not its victim's. A refusal with no source address falls back to the claim.
    """
    alias = subject_aliases(events)
    counts: dict[str, int] = {}
    for event in events:
        if event.get("type") == "auth_denied":
            sender = event.get("source_ip") or event.get("device_id")
            if isinstance(sender, str):
                sender = alias.get(sender, sender)
                counts[sender] = counts.get(sender, 0) + 1
    return counts


def _subject_row(
    result: SubjectResult,
    quarantined_at: float | None,
    events: Sequence[Event],
    refused: int | None = None,
) -> dict[str, Any]:
    isolation = None
    if quarantined_at is not None and result.onset_s is not None:
        isolation = quarantined_at - result.onset_s
    after = None
    if quarantined_at is not None and result.kind == "node":
        after = routed_after(events, result.subject, quarantined_at)
    row = {
        "subject": result.subject,
        "kind": result.kind,
        "truth": result.truth,
        "predicted": result.predicted,
        "correct": result.correct,
        "family_correct": result.family_correct,
        "onset_s": result.onset_s,
        "detection_latency_s": result.detection_latency_s,
        "quarantined_at_s": quarantined_at,
        "isolation_latency_s": isolation,
        "routed_after_quarantine": after,
    }
    if result.kind == "client":
        row["refused_at_admission"] = refused or 0
    return row


def score_recording(
    events: Sequence[Event],
    *,
    slo_ms: float | None = None,
    window_cycles: int = DEFAULT_WINDOW_CYCLES,
) -> dict[str, Any]:
    """Score a recording: who was caught, how fast, and at what cost.

    Returns plain JSON-safe data. ``attack_results`` holds the classifier's
    :class:`SubjectResult` objects for the detailed report and is dropped
    from ``--json`` output.
    """
    deadline = slo_ms if slo_ms is not None else recorded_slo_ms(events)
    totals = service_totals(events, deadline)
    nfr = score_nfr(totals)
    availability = score_availability(totals)

    results = score_run(events, window_cycles=window_cycles)
    quarantines = first_quarantine(events)
    refusals = refused_at_admission(events)
    subjects = [
        _subject_row(r, quarantines.get(r.subject), events, refusals.get(r.subject))
        for r in results
    ]
    attackers = [s for s in subjects if s["truth"] != NO_ATTACK]
    honest = [s for s in subjects if s["truth"] == NO_ATTACK]

    detection: dict[str, Any] = {
        "attackers": len(attackers),
        "attackers_named": sum(1 for s in attackers if s["correct"]),
        "attackers_in_family": sum(1 for s in attackers if s["family_correct"]),
        "attackers_quarantined": sum(1 for s in attackers if s["quarantined_at_s"] is not None),
        "attackers_cut_off": sum(1 for s in attackers if s["routed_after_quarantine"] == 0),
        "honest": len(honest),
        "honest_mislabelled": sum(1 for s in honest if not s["correct"]),
        "honest_quarantined": sum(1 for s in honest if s["quarantined_at_s"] is not None),
        "window_cycles": window_cycles,
    }
    # Only a recording with IoT clients has an admission check to report on.
    if any(s["kind"] == "client" for s in subjects):
        detection["admission"] = {
            "refused": sum(refusals.values()),
            "refused_attackers": sum(s.get("refused_at_admission", 0) for s in attackers),
            "refused_honest": sum(s.get("refused_at_admission", 0) for s in honest),
        }

    return {
        "recording": _header(events),
        "service": {
            "offered": nfr["offered"],
            "completed": availability["completed"],
            "failed": nfr["failed"],
            "availability": availability["availability"],
            "failure_rate": nfr["failure_rate"],
            "slo_ms": deadline,
            "slo_violation_rate": nfr["slo_violation_rate"],
            "mean_latency_ms": nfr["mean_latency_ms"],
            "p95_latency_ms": nfr["p95_latency_ms"],
            "attacker_share": attacker_share(events),
        },
        "detection": detection,
        "subjects": subjects,
        "attack_results": results,
    }


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, JSON_DECIMALS)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def to_json(scores: dict[str, Any]) -> str:
    """The scores as stable, sorted JSON with floats rounded to :data:`JSON_DECIMALS`."""
    public = {k: v for k, v in scores.items() if k != "attack_results"}
    return json.dumps(_rounded(public), indent=2, sort_keys=True)


def _seconds(value: float | None) -> str:
    if value is None:
        return "never"
    return f"{value:.1f} s"


def _traffic_after(count: int | None) -> str:
    if count == 0:
        return "no traffic after that"
    if count == 1:
        return "1 task still routed to it after that"
    return f"{count:,} tasks still routed to it after that"


def _verdict(subject: dict[str, Any]) -> str:
    if subject["correct"]:
        return "named correctly"
    if subject["family_correct"]:
        return "right family"
    return "missed"


def format_scores(scores: dict[str, Any], name: str) -> str:
    """The human-readable summary ``turncoat score`` prints."""
    rec = scores["recording"]
    svc = scores["service"]
    det = scores["detection"]
    out: list[str] = []
    add = out.append

    made = [rec.get("backend", "?") + " backend"]
    for key in ("strategy", "scenario"):
        if rec.get(key):
            made.append(f"{key} {rec[key]}")
    if rec.get("seed") is not None:
        made.append(f"seed {rec['seed']}")
    add(f"{name}  ({', '.join(made)})")
    add("")

    add("Service")
    add(f"  Tasks offered         {svc['offered']:>8,}")
    add(f"  Completed             {svc['completed']:>8,}   {svc['availability']:.2%} availability")
    add(f"  Failed                {svc['failed']:>8,}   {svc['failure_rate']:.2%}")
    add(
        f"  SLO violations        {svc['slo_violation_rate']:>8.2%}   deadline {svc['slo_ms']:g} ms"
    )
    add(
        f"  Latency, mean / p95   {svc['mean_latency_ms']:>8.1f}   / {svc['p95_latency_ms']:.1f} ms"
    )
    if svc["attacker_share"] is not None:
        add(f"  Routed to attackers   {svc['attacker_share']:>8.2%}")
    add("")

    add("Attackers")
    attackers = [s for s in scores["subjects"] if s["truth"] != NO_ATTACK]
    if not attackers:
        add("  none in the ground truth")
    for s in attackers:
        add(f"  {s['subject']:<8} {s['truth']:<10} {_verdict(s)} as {s['predicted']}")
        add(f"           detected {_seconds(s['detection_latency_s'])} after onset")
        if s["kind"] == "client":
            refused = s["refused_at_admission"]
            add(f"           {refused:,} request{'' if refused == 1 else 's'} refused at admission")
        elif s["quarantined_at_s"] is None:
            add("           never flagged for quarantine")
        else:
            add(
                f"           flagged for quarantine {_seconds(s['isolation_latency_s'])} "
                f"after onset; {_traffic_after(s['routed_after_quarantine'])}"
            )
    add("")
    add(
        f"Detection: {det['attackers_named']} of {det['attackers']} attackers named correctly, "
        f"{det['attackers_quarantined']} flagged, {det['attackers_cut_off']} cut off; "
        f"{det['honest_mislabelled']} of {det['honest']} honest subjects mislabelled, "
        f"{det['honest_quarantined']} flagged."
    )
    admission = det.get("admission")
    if admission is not None:
        add(
            f"Admission: {admission['refused']:,} requests refused, "
            f"{admission['refused_attackers']:,} from attackers and "
            f"{admission['refused_honest']:,} from honest devices."
        )
    return "\n".join(out)


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        "score",
        help="grade a recording: who was caught, how fast, at what cost",
        description=(
            "Grade an events.jsonl recording against the ground truth it carries: which "
            "attackers were named and quarantined, how long after onset, and what the run "
            "cost in failures, SLO violations and latency."
        ),
        epilog="Exit status: 0 when scored, 1 when the recording is invalid or has no ground "
        "truth, 2 when it cannot be read.",
    )
    parser.add_argument("path", metavar="RECORDING", help="JSONL recording to score")
    parser.add_argument(
        "--json", action="store_true", help="print the scores as JSON instead of a summary"
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="also print the full attack report: confusion matrix and per-class metrics",
    )
    parser.add_argument(
        "--slo-ms",
        type=float,
        default=None,
        metavar="MS",
        help=f"SLO deadline (default: the recording's, else {DEFAULT_SLO_MS:g})",
    )
    parser.add_argument(
        "--window-cycles",
        type=int,
        default=DEFAULT_WINDOW_CYCLES,
        metavar="N",
        help=f"attack classifier evidence window, in poll cycles (default {DEFAULT_WINDOW_CYCLES})",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="score even if the recording fails validation",
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    try:
        report = validate_file(args.path)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{args.path}: cannot read: {getattr(exc, 'strerror', None) or exc}")
        return EXIT_UNREADABLE

    if not report.ok and not args.skip_validation:
        print(report.format(args.path))
        print("turncoat score: fix the recording, or pass --skip-validation to score it anyway.")
        return EXIT_FAILED

    events = read_events(args.path)
    if not ground_truth(events):
        print(f"{args.path}: no topology event, so there is no ground truth to score against.")
        return EXIT_FAILED

    if args.slo_ms is not None and not args.slo_ms > 0:
        print("turncoat score: --slo-ms must be a positive number of milliseconds")
        return EXIT_FAILED

    scores = score_recording(events, slo_ms=args.slo_ms, window_cycles=args.window_cycles)
    if args.json:
        print(to_json(scores))
        return EXIT_OK

    print(format_scores(scores, args.path))
    if args.detail:
        print()
        print(format_report(scores["attack_results"], window_cycles=args.window_cycles))
    return EXIT_OK


__all__ = [
    "DEFAULT_SLO_MS",
    "attacker_share",
    "first_quarantine",
    "format_scores",
    "recorded_slo_ms",
    "refused_at_admission",
    "routed_after",
    "score_recording",
    "service_totals",
    "to_json",
]
