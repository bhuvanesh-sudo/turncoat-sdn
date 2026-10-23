"""Attack-classification scoring for a JSONL event recording.

Ported from the final-year project's ``evaluation/attack_report.py``. The
scoring logic is unchanged; only internal notes were left behind.

Answers not "was this node quarantined" but "attack X was detected on node Y at
time T, classified as [type]" -- and then scores those labels against ground
truth, so the classification claim has a confusion matrix behind it rather
than an assertion.

Replays rather than summarises
------------------------------
The obvious implementation would tally the ``classification`` events a live
controller publishes. Those are published on the rising edge only, so they
record label *changes*, not the label at each moment, and a tally would weight
a subject that flapped once exactly like one that held a verdict all run.

Instead this rebuilds the evidence windows from the raw detector output and
re-runs :mod:`turncoat_sdn.scoring.attack_classifier` over them cycle by cycle,
exactly as the live path would have. Two things fall out of that:

* a detection latency per attack -- ground-truth onset (``attack_start_s``) to
  the first cycle at which the classifier would have named the attack
  correctly. On a live testbed read this as an UPPER BOUND: onset is measured
  from the moment an agent launches, while the recording's t0 is the moment
  the controller started, a few seconds earlier. In the simulator both clocks
  start together, so the figure is exact to the poll interval.
* a run verdict that reflects how long each label actually held, instead of
  whichever label happened to be published last.

It also means the offline number cannot silently disagree with the live one:
same classifier, same thresholds, one implementation.

Cycle reconstruction
--------------------
``anomaly`` events carry the signals but are only emitted when something
fires, so on their own they contain no clean cycles -- and without clean cycles
the on-off rule cannot see an off phase (see ``attack_classifier.Observation``).
The missing beat comes from ``node_status``, published once per poll cycle
unconditionally: every ``anomaly`` seen since the previous ``node_status``
belongs to the cycle that ``node_status`` closes.

Run::

    python -m turncoat_sdn.scoring.attack_report run.jsonl
    python -m turncoat_sdn.scoring.attack_report run.jsonl --csv subjects.csv

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from turncoat_sdn.scoring.attack_classifier import (
    ALL_LABELS,
    DEFAULT_WINDOW_CYCLES,
    GROUND_TRUTH_ALIASES,
    NO_ATTACK,
    SIG_AUTH_BAD_RESPONSE,
    SIG_AUTH_IP_PIN,
    SIG_FLOOD,
    Classifier,
    Observation,
    classify_client,
    classify_node,
    family_of,
)

Event = dict[str, Any]

# The live authenticator's AUTH_DENY_* tags, as plain strings so this analysis
# runs with no controller stack installed.
AUTH_KIND_IP_PIN = "ip_pin"
AUTH_KIND_BAD_RESPONSE = "bad_response"


@dataclass
class SubjectResult:
    """What the classifier concluded about one node or device over the run."""

    subject: str
    kind: str  # 'node' | 'client'
    truth: str
    predicted: str
    #: How many cycles each label held. The run verdict is the modal label,
    #: NOT the final one: an on-off attacker is correctly abstained on while
    #: it is in a good phase, so whichever label happens to be standing when
    #: the recording ends says more about where the run was cut than about
    #: what the system concluded.
    label_cycles: dict[str, int] = field(default_factory=dict)
    abstained_cycles: int = 0
    total_cycles: int = 0
    #: Ground-truth onset (``attack_start_s``), when the recording carries it.
    onset_s: float | None = None
    #: First cycle time, from run start, at which the classifier named `truth`.
    first_correct_t: float | None = None
    #: first_correct_t - onset. None when either end is unknown.
    detection_latency_s: float | None = None
    rationale: str = ""

    @property
    def correct(self) -> bool:
        return self.predicted == self.truth

    @property
    def family_correct(self) -> bool:
        """Right kind of attack, even if the exact label is wrong.

        Reported alongside `correct` because the two sibling pairs are
        separable only by evidence the defence can legitimately deny us -- a
        blackhole contained in seconds yields too few outcomes to prove it was
        not a grayhole (see attack_classifier._split_drop_family). Collapsing
        that into the same "MISS" as a total abstention would overstate the
        failure; scoring only the family would understate it. Both are printed.
        """
        return family_of(self.predicted) == family_of(self.truth)


def _topology_nodes(events: Sequence[Event]) -> list[dict[str, Any]]:
    """The node list of the first ``topology`` event, or an empty list."""
    for ev in events:
        if ev.get("type") == "topology":
            return list(ev.get("graph", {}).get("nodes", []))
    return []


def ground_truth(events: Sequence[Event]) -> dict[str, tuple[str, str]]:
    """subject -> (kind, label), from the first ``topology`` event.

    The topology event carries an ``attack`` field on every server and every
    IoT node. Config strings are mapped through GROUND_TRUTH_ALIASES so the
    historical ``drop`` becomes the standard ``blackhole`` the report speaks in.
    """
    truth: dict[str, tuple[str, str]] = {}
    for node in _topology_nodes(events):
        kind = node.get("kind")
        if kind not in ("server", "iot"):
            continue
        raw = node.get("attack", "none") or "none"
        truth[node["id"]] = (
            "node" if kind == "server" else "client",
            GROUND_TRUTH_ALIASES.get(raw, raw),
        )
    return truth


def onset_times(events: Sequence[Event]) -> dict[str, float]:
    """subject -> attack onset in seconds from run start, if recorded.

    Absent, detection latency is reported as unknown rather than guessed from
    the first anomaly, which would make every detector look infinitely fast by
    definition.
    """
    return {
        node["id"]: float(node["attack_start_s"])
        for node in _topology_nodes(events)
        if "attack_start_s" in node
    }


def _run_start(events: Sequence[Event]) -> float:
    for ev in events:
        t = ev.get("ts")
        if isinstance(t, (int, float)):
            return float(t)
    return 0.0


def node_cycles(
    events: Sequence[Event],
    node_ids: Sequence[str],
) -> dict[str, list[Observation]]:
    """Per-node per-cycle observations, clean cycles included.

    See the module docstring: ``node_status`` is the per-cycle heartbeat that
    turns a sparse stream of ``anomaly`` events into a dense timeline.
    """
    windows: dict[str, list[Observation]] = {n: [] for n in node_ids}
    pending: dict[str, dict[str, float]] = {}

    for ev in events:
        etype = ev.get("type")
        if etype == "anomaly":
            node = ev.get("node")
            if node in windows:
                # An anomaly with no structured signals still means "flagged,
                # cause unknown": an empty dict would read as a CLEAN cycle and
                # quietly turn a detection into a non-detection, which is the
                # one direction of error this report must never make silently.
                signals = ev.get("signals")
                pending[node] = dict(signals) if signals else {"_unstructured": 1.0}
        elif etype == "node_status":
            t = float(ev.get("ts", 0.0))
            for node in windows:
                windows[node].append(Observation(t, pending.get(node, {})))
            pending.clear()

    return windows


def client_observations(events: Sequence[Event]) -> dict[str, list[Observation]]:
    """Per-device observations from ``flood`` and ``auth_denied`` events.

    Sparse by nature and that is correct here: unlike a node, which is polled
    on a fixed beat, a device only produces evidence when it does something.
    Neither client-side rule depends on counting clean cycles.

    Keyed by CLIENT IP for flood events and by SOURCE IP (falling back to the
    claimed device id) for auth events, matching what each detector observes.
    ``subject_aliases`` maps IPs back to device ids.
    """
    windows: dict[str, list[Observation]] = {}

    def add(subject: str, t: float, signals: dict[str, float]) -> None:
        windows.setdefault(subject, []).append(Observation(t, signals))

    for ev in events:
        etype = ev.get("type")
        t = float(ev.get("ts", 0.0))
        if etype == "flood":
            client = ev.get("client_ip")
            if client:
                ratio = ev.get("ratio")
                add(client, t, {SIG_FLOOD: float(ratio) if ratio else 0.0})
        elif etype == "auth_denied":
            # Keyed by the host that sent the request, not the identity it
            # claimed: keying on the claim files a spoofing attempt under the
            # impersonated victim.
            subject = ev.get("source_ip") or ev.get("device_id")
            if not subject:
                continue
            kind = ev.get("kind")
            if kind == AUTH_KIND_IP_PIN:
                add(subject, t, {SIG_AUTH_IP_PIN: 1.0})
            elif kind == AUTH_KIND_BAD_RESPONSE:
                add(subject, t, {SIG_AUTH_BAD_RESPONSE: 1.0})
            else:
                add(subject, t, {})

    return windows


def subject_aliases(events: Sequence[Event]) -> dict[str, str]:
    """IP -> device id, from the topology event's iot nodes.

    Flood evidence arrives keyed by source IP while ground truth is keyed by
    device id; without this the flooding device would score as an unknown
    subject and its ground-truth row would come out as a silent miss.
    """
    return {
        node["ip"]: node["id"]
        for node in _topology_nodes(events)
        if node.get("kind") == "iot" and node.get("ip")
    }


def _replay(
    window: Sequence[Observation],
    truth: str,
    classify: Classifier,
    window_cycles: int,
) -> tuple[dict[str, int], int, float | None, str]:
    """Re-run the classifier cycle by cycle over a bounded sliding window.

    Returns (label_cycles, abstained_cycles, first_correct_t, last_rationale).
    Mirrors the live path's bounded deque exactly rather than classifying the
    whole run at once, so the offline verdict is reachable online.
    """
    rolling: deque[Observation] = deque(maxlen=window_cycles)
    label_cycles: Counter[str] = Counter()
    abstained = 0
    first_correct_t: float | None = None
    last_rationale = ""

    for obs in window:
        rolling.append(obs)
        # now=None: the recording is finished, so the staleness clock is not
        # meaningful here. The newest observation in `rolling` IS the cycle
        # being replayed.
        result = classify(list(rolling), now=None)
        if result is None:
            abstained += 1
            continue
        label_cycles[result.attack_type] += 1
        last_rationale = result.rationale
        if result.attack_type == truth and first_correct_t is None:
            first_correct_t = obs.t

    return dict(label_cycles), abstained, first_correct_t, last_rationale


def score_run(
    events: Sequence[Event],
    window_cycles: int = DEFAULT_WINDOW_CYCLES,
) -> list[SubjectResult]:
    """Classify every subject in the recording and score against ground truth."""
    truth = ground_truth(events)
    onsets = onset_times(events)
    alias = subject_aliases(events)
    t0 = _run_start(events)

    node_ids = [s for s, (kind, _) in truth.items() if kind == "node"]
    windows = node_cycles(events, node_ids)
    client_windows = client_observations(events)

    # Fold IP-keyed evidence onto the device id ground truth is keyed by.
    folded: dict[str, list[Observation]] = {}
    for subject, obs in client_windows.items():
        folded.setdefault(alias.get(subject, subject), []).extend(obs)
    for obs in folded.values():
        obs.sort(key=lambda o: o.t)

    results: list[SubjectResult] = []

    for subject, (kind, subject_truth) in sorted(truth.items()):
        if kind == "node":
            window = windows.get(subject, [])
            classify: Classifier = classify_node
        else:
            window = folded.get(subject, [])
            classify = classify_client

        label_cycles, abstained, first_correct_t, rationale = _replay(
            window,
            subject_truth,
            classify,
            window_cycles,
        )

        predicted = (
            max(label_cycles.items(), key=lambda kv: kv[1])[0] if label_cycles else NO_ATTACK
        )

        onset = onsets.get(subject)
        latency = (
            (first_correct_t - t0) - onset
            if first_correct_t is not None and onset is not None
            else None
        )

        results.append(
            SubjectResult(
                subject=subject,
                kind=kind,
                truth=subject_truth,
                predicted=predicted,
                label_cycles=label_cycles,
                abstained_cycles=abstained,
                total_cycles=len(window),
                onset_s=onset,
                first_correct_t=(first_correct_t - t0 if first_correct_t is not None else None),
                detection_latency_s=latency,
                rationale=rationale,
            )
        )

    return results


def confusion_matrix(results: Sequence[SubjectResult]) -> dict[str, dict[str, int]]:
    """truth -> predicted -> count, over the labels actually present.

    Restricted to labels that appear in this run rather than always printing
    all nine: a matrix that is mostly zeros because the run did not configure
    those attacks reads as poor performance at a glance when it is nothing of
    the sort.
    """
    present = [
        lab for lab in ALL_LABELS if any(r.truth == lab or r.predicted == lab for r in results)
    ]
    matrix = {t: dict.fromkeys(present, 0) for t in present}
    for r in results:
        matrix.setdefault(r.truth, dict.fromkeys(present, 0))
        matrix[r.truth][r.predicted] = matrix[r.truth].get(r.predicted, 0) + 1
    return matrix


def per_class_metrics(results: Sequence[SubjectResult]) -> dict[str, dict[str, float]]:
    """Precision / recall / F1 / support per label.

    NO_ATTACK is scored like any other class on purpose. It is the class that
    catches false accusations of honest nodes, which is the failure mode that
    matters most: a system can have every detector right and still wrongly
    condemn honest servers.
    """
    labels = sorted({r.truth for r in results} | {r.predicted for r in results})
    out: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = sum(1 for r in results if r.truth == label and r.predicted == label)
        fp = sum(1 for r in results if r.truth != label and r.predicted == label)
        fn = sum(1 for r in results if r.truth == label and r.predicted != label)
        support = sum(1 for r in results if r.truth == label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": float(support),
        }
    return out


def format_report(
    results: Sequence[SubjectResult],
    window_cycles: int = DEFAULT_WINDOW_CYCLES,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 78)
    add("ATTACK CLASSIFICATION REPORT".center(78))
    add("=" * 78)
    add(f"Subjects scored: {len(results)}   replay window: {window_cycles} cycles")
    add("")

    add("-" * 78)
    add("PER-SUBJECT")
    add("-" * 78)
    add(f"{'subject':<10} {'truth':<16} {'predicted':<16} {'hit':<6} {'cycles':<8} {'detect':<9}")
    for r in sorted(results, key=lambda x: (x.truth == NO_ATTACK, x.subject)):
        latency = (
            f"{r.detection_latency_s:+.1f}s"
            if r.detection_latency_s is not None
            else ("-" if r.truth == NO_ATTACK else "n/a")
        )
        # FAMILY = the exact label is wrong but the kind of attack is right.
        hit = "OK" if r.correct else ("FAMILY" if r.family_correct else "MISS")
        add(
            f"{r.subject:<10} {r.truth:<16} {r.predicted:<16} "
            f"{hit:<6} {r.total_cycles:<8} {latency:<9}"
        )
    add("")

    add("-" * 78)
    add("CONFUSION MATRIX  (rows = ground truth, cols = predicted)")
    add("-" * 78)
    matrix = confusion_matrix(results)
    if matrix:
        labels = list(matrix)
        width = max(len(lab) for lab in labels) + 2
        header = " " * width + "".join(f"{lab[:9]:>10}" for lab in labels)
        add(header)
        for t in labels:
            row = "".join(f"{matrix[t].get(p, 0):>10}" for p in labels)
            add(f"{t:<{width}}{row}")
    add("")

    add("-" * 78)
    add("PER-CLASS")
    add("-" * 78)
    add(f"{'label':<18} {'precision':>10} {'recall':>10} {'f1':>10} {'support':>9}")
    metrics = per_class_metrics(results)
    for label, m in metrics.items():
        add(
            f"{label:<18} {m['precision']:>10.3f} {m['recall']:>10.3f} "
            f"{m['f1']:>10.3f} {int(m['support']):>9}"
        )
    add("")

    correct = sum(1 for r in results if r.correct)
    total = len(results)
    add(f"Overall accuracy: {correct}/{total} = {(correct / total if total else 0.0):.1%}")

    attacks = [r for r in results if r.truth != NO_ATTACK]
    if attacks:
        detected = [r for r in attacks if r.predicted != NO_ATTACK]
        add(f"Attacks detected at all (any label): {len(detected)}/{len(attacks)}")
        add(
            f"Attacks placed in the right family:  "
            f"{sum(1 for r in attacks if r.family_correct)}/{len(attacks)}"
        )
        add(
            f"Attacks classified correctly:        "
            f"{sum(1 for r in attacks if r.correct)}/{len(attacks)}"
        )
        latencies = [r.detection_latency_s for r in attacks if r.detection_latency_s is not None]
        if latencies:
            add(
                f"Detection latency: mean {sum(latencies) / len(latencies):.1f}s, "
                f"max {max(latencies):.1f}s   [UPPER BOUND on a live run -- measured "
                f"from controller"
            )
            add(
                "                   start, so it includes the testbed build time "
                "before agents launch; see this module's docstring.]"
            )
        else:
            add(
                "Detection latency: not computable -- the recording carries no "
                "attack_start_s ground truth."
            )

    honest = [r for r in results if r.truth == NO_ATTACK]
    if honest:
        accused = [r for r in honest if r.predicted != NO_ATTACK]
        add(
            f"Honest subjects wrongly labelled:    {len(accused)}/{len(honest)}"
            + (
                f"  ({', '.join(f'{r.subject}->{r.predicted}' for r in accused)})"
                if accused
                else ""
            )
        )
    add("=" * 78)
    return "\n".join(lines)


def write_csv(results: Sequence[SubjectResult], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "subject",
                "kind",
                "truth",
                "predicted",
                "correct",
                "total_cycles",
                "abstained_cycles",
                "onset_s",
                "first_correct_t",
                "detection_latency_s",
                "rationale",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.subject,
                    r.kind,
                    r.truth,
                    r.predicted,
                    int(r.correct),
                    r.total_cycles,
                    r.abstained_cycles,
                    "" if r.onset_s is None else f"{r.onset_s:.2f}",
                    "" if r.first_correct_t is None else f"{r.first_correct_t:.2f}",
                    "" if r.detection_latency_s is None else f"{r.detection_latency_s:.2f}",
                    r.rationale,
                ]
            )


def _read_jsonl(path: str) -> list[Event]:
    """Parse a JSONL recording, skipping blank and malformed lines.

    A run killed mid-write can leave one truncated tail line, and that must not
    fail the whole report. Stands in until the shared reader in
    :mod:`turncoat_sdn.events` lands.
    """
    events: list[Event] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score attack classification against ground truth.",
    )
    parser.add_argument("events", help="path to a JSONL event recording")
    parser.add_argument(
        "--window-cycles",
        type=int,
        default=DEFAULT_WINDOW_CYCLES,
        help=f"sliding evidence window, in detection cycles (default {DEFAULT_WINDOW_CYCLES})",
    )
    parser.add_argument("--csv", help="also write per-subject rows to this path")
    args = parser.parse_args(argv)

    events = _read_jsonl(args.events)
    if not events:
        print(f"No events found in {args.events}")
        return 1

    if not ground_truth(events):
        print(
            f"No `topology` event in {args.events} -- ground truth is what this "
            f"report scores against, so there is nothing to score. Re-run with a "
            f"recording that includes the run start."
        )
        return 1

    results = score_run(events, window_cycles=args.window_cycles)
    print(format_report(results, window_cycles=args.window_cycles))

    if args.csv:
        write_csv(results, args.csv)
        print(f"\nPer-subject rows written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
