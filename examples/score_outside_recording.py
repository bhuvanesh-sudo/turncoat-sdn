"""Grade a system that is not ours: score a recording turncoat-sdn did not write.

The benchmark grades whatever writes the shared ``events.jsonl`` format. To
show that nothing else is needed, the toy controller below stands in for your
own system. It imports nothing from turncoat-sdn and writes plain JSON lines
with the standard library, as any controller in any language could: three
servers, round-robin routing, and a timeout check that quarantines a server
once all of its last five tasks have timed out. Its ``srv3`` turns
into a blackhole 20 seconds in.

Then turncoat-sdn takes over, exactly as for a simulated run: it validates
the file, scores it against the ground truth in its ``topology`` line, and
prints the same report ``turncoat score`` does.

Run it from the repository root:

    python examples/score_outside_recording.py                 # writes outside.jsonl
    python examples/score_outside_recording.py -o my_run.jsonl
    turncoat score my_run.jsonl

What a recording must hold is in docs/event-format.md; how to plug in your
own system is in docs/extending.md.
"""

from __future__ import annotations

import argparse
import json
from collections import deque

# --- Your system: knows nothing about turncoat-sdn ---------------------------

SERVERS, ONSET, RUN_S, RATE_HZ = ("srv1", "srv2", "srv3"), 20.0, 60.0, 10


def outside_controller(path: str) -> None:
    """Run the toy controller for RUN_S seconds and log every decision as JSON lines."""
    events = []  # (ts, order, event): sorted by time before writing

    def log(ts, kind, **fields):
        events.append((round(ts, 3), len(events), {"type": kind, "ts": round(ts, 3), **fields}))

    nodes = [{"id": s, "kind": "server", "attack": "none"} for s in SERVERS]
    nodes[2].update(attack="blackhole", attack_start_s=ONSET)  # the ground truth
    log(0.0, "topology", graph={"nodes": nodes, "links": []})
    recent = {s: deque(maxlen=5) for s in SERVERS}
    quarantined, turn = set(), 0
    for task in range(1, int(RUN_S * RATE_HZ) + 1):
        now = task / RATE_HZ
        if task % RATE_HZ == 0:  # once a second: check every server, close the cycle
            for s in SERVERS:
                rate = recent[s].count("timeout") / max(1, len(recent[s]))
                if rate > 0.8:
                    log(now, "anomaly", node=s, signals={"packet_drop": rate})
                    if s not in quarantined:
                        quarantined.add(s)
                        log(now, "quarantine", node=s)
            log(now, "node_status", nodes={s: {"quarantined": s in quarantined} for s in SERVERS})
        live = [s for s in SERVERS if s not in quarantined]
        chosen, turn = live[turn % len(live)], turn + 1
        log(now, "route", task=task, chosen=chosen)
        dropped = chosen == "srv3" and now >= ONSET
        latency = 2000.0 if dropped else 180.0
        log(
            now + latency / 1000,
            "report",
            task=task,
            node=chosen,
            latency_ms=latency,
            status="timeout" if dropped else "success",
        )
        recent[chosen].append("timeout" if dropped else "success")
    header = {"type": "header", "schema_version": "1.0", "backend": "live", "strategy": "toy_rr"}
    with open(path, "w", encoding="utf-8") as f:
        for line in [header] + [e for _, _, e in sorted(events, key=lambda x: x[:2])]:
            f.write(json.dumps(line) + "\n")


# --- turncoat-sdn: grades it like any other run ------------------------------


def grade(path: str) -> int:
    from turncoat_sdn.cli.score import format_scores, score_recording
    from turncoat_sdn.events import read_events
    from turncoat_sdn.events.validate import validate_file

    report = validate_file(path)
    print(report.format(path))
    if not report.ok:
        return 1
    events = read_events(path)
    print(format_scores(score_recording(events), path))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a recording from an outside system.")
    parser.add_argument("-o", "--output", default="outside.jsonl", help="recording to write")
    args = parser.parse_args()
    outside_controller(args.output)
    raise SystemExit(grade(args.output))
