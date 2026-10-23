# Scoring

**Owner:** arv · **Written in:** v0.2 · **Attack scoring:** ash

## What it is

The scoring package converts simulation results into measurements that can be compared across load-balancing strategies. It covers non-functional requirements (NFR), availability, and metrics measured over fixed time intervals. [Attack scoring](#attack-scoring), below, grades a recording's attack detections against ground truth.

The implementation lives in `turncoat_sdn.scoring`. Its functions accept in-memory Python data and return calculated metrics.

## Why it exists

Raw simulation results do not always make it easy to compare strategies. One strategy might complete more tasks, while another might have lower latency or fewer SLO violations.

Scoring converts task outcomes into consistent measurements so the reliability, performance, and availability of different strategies can be evaluated.

## How to use it

```python
from turncoat_sdn.scoring import (
    score_availability,
    score_intervals,
    score_nfr,
)

run = {
    "offered": 100,
    "completed": 94,
    "failed": 6,
    "slo_violations": 8,
    "latencies_ms": [40.0, 45.0, 50.0, 60.0, 80.0],
}

print(score_nfr(run))
print(score_availability(run))

samples = [
    {"timestamp_s": 1.0, "latency_ms": 40.0, "completed": 1},
    {"timestamp_s": 2.0, "latency_ms": 60.0, "completed": 1},
    {"timestamp_s": 6.0, "latency_ms": 80.0, "completed": 1},
]

print(score_intervals(samples, interval_s=5.0))
```

## How it works inside

### Non-functional requirements

`score_nfr(record)` expects `offered`, `failed`, `slo_violations`, and `latencies_ms`.

The failure rate is:

```text
failure_rate = failed / offered
```

The SLO violation rate is:

```text
slo_violation_rate = slo_violations / offered
```

Both rates use the number of offered tasks as the denominator. When no tasks were offered, the rates are zero.

The scorer also calculates the number of latency samples, mean latency, and p95 latency. Empty latency samples produce zero latency summaries. Latencies must be finite and non-negative, and task counts must be valid.

### Availability

`score_availability(record)` expects `offered` and `completed`.

Availability is calculated as:

```text
availability = completed / offered
```

The result also reports the number of tasks that did not complete. If no tasks were offered, availability is zero.

This measures task-completion availability, not time-based service uptime.

### Interval scoring

`score_intervals(samples, interval_s, timestamp_key="timestamp_s")` groups timestamped samples into fixed-width intervals starting at time zero.

For a five-second interval width, timestamps from 0 up to, but not including, 5 seconds belong to the first interval. Timestamps from 5 up to, but not including, 10 seconds belong to the second interval.

Numeric metrics are averaged within each interval. This makes it possible to analyse changes in latency and other measurements over time.

The interval width must be positive, and timestamps and metric values must be valid numeric values.

## Integration status

The current functions operate on in-memory records. They do not directly read `events.jsonl` or define the shared event schema.

Integration with the simulator's `RunResult`, the shared event format, and validation against the original final-year project reports remain to be completed.


## Attack scoring

### What it is

The attack scorer replays a recording's detector evidence through the attack
classifier and scores every server and IoT device against the ground truth
written at the start of the run. It prints a per-subject table, a confusion
matrix, per-class precision, recall and F1, and a detection latency for each
attack.

Two modules, both moved from the final-year project without logic changes:

| Module | Holds | Ported from |
|---|---|---|
| `scoring/attack_classifier.py` | `classify_node`, `classify_client`, the labels and their families, `AttackEvidence` | `controller/attack_classifier.py` |
| `scoring/attack_report.py` | `score_run`, `confusion_matrix`, `per_class_metrics`, `format_report`, `write_csv` | `evaluation/attack_report.py` |

### Why it exists

A quarantine says *something* was wrong with a node. It does not say the
system knew what. "srv3 was quarantined" and "srv3 was correctly named a
grayhole 14 s after it turned" are different claims, and only the second can be
checked against the truth. The scorer turns detections into labels and the
labels into a confusion matrix, so a strategy's detection claim comes with
numbers behind it.

It also keeps the offline score honest: the scorer calls the same classifier a
live controller calls, so a recording cannot score better offline than the
system could have done online.

### How to use it

Pass `score_run` the run's events, as a list of dicts. This recording has two
servers. `srv1` is a Sybil that turns at 2 s, and the latency tell flags it from
the fourth poll:

```python
from turncoat_sdn.scoring.attack_report import score_run

servers = [
    {"id": "srv1", "kind": "server", "attack": "sybil", "attack_start_s": 2.0},
    {"id": "srv2", "kind": "server", "attack": "none"},
]
flagged = {"latency_tell": 4.4}  # srv1 answers 4.4x slower than the fleet

events = [{"ts": 0.0, "type": "topology", "graph": {"nodes": servers}}]
for t in range(1, 11):
    if t >= 4:
        events.append({"ts": t, "type": "anomaly", "node": "srv1", "signals": flagged})
    events.append({"ts": t, "type": "node_status"})  # closes the poll cycle

for r in score_run(events):
    print(r.subject, r.truth, r.predicted, r.detection_latency_s)
# srv1 sybil sybil 2.0
# srv2 none none None
```

`format_report(score_run(events))` prints the full report. To score a file:

```bash
python -m turncoat_sdn.scoring.attack_report run.jsonl
python -m turncoat_sdn.scoring.attack_report run.jsonl --csv subjects.csv
```

`turncoat score --detail run.jsonl` prints the same report after its own
summary (see `docs/cli.md`).

Here is the report for a simulated `both` run (8 servers, seed 1000, a Sybil on
`srv8` and a dropper on `srv7`). It is produced by
`tests/scoring/test_attack_report.py::TestSimulatedRun`:

```
------------------------------------------------------------------------------
PER-SUBJECT
------------------------------------------------------------------------------
subject    truth            predicted        hit    cycles   detect
srv7       blackhole        blackhole        OK     120      +3.0s
srv8       sybil            sybil            OK     120      +3.0s
srv1       none             none             OK     120      -
...
------------------------------------------------------------------------------
CONFUSION MATRIX  (rows = ground truth, cols = predicted)
------------------------------------------------------------------------------
                sybil blackhole      none
sybil               1         0         0
blackhole           0         1         0
none                0         0         6
...
Overall accuracy: 8/8 = 100.0%
Detection latency: mean 3.0s, max 3.0s
Honest subjects wrongly labelled:    0/6
```

Both attackers are named on the third poll, the same moment the simulator
records them isolated (`time_to_isolate_s = 3.0`).

### How it works inside

**What it reads.** Until the v0.2 event schema is written down (arj), the
scorer reads the events in the shape the final-year project's controller
wrote them:

| Event | Fields read | Used for |
|---|---|---|
| `topology` (first one only) | `graph.nodes[]`: `id`, `kind` (`server` or `iot`), `attack`, `attack_start_s`, `ip` | Ground truth, onset, IP-to-device mapping |
| `anomaly` | `node`, `signals` | A server's flagged cycle |
| `node_status` | `ts` | The heartbeat that closes one poll cycle |
| `flood` | `client_ip`, `ratio` | A device's flood evidence |
| `auth_denied` | `source_ip` (or `device_id`), `kind` | A device's spoof or bad-credentials evidence |

The first event's `ts` is the run's t0.

**Cycles, clean ones included.** An `anomaly` event appears only when a
detector fires. Every `anomaly` seen since the previous `node_status` belongs
to the cycle that `node_status` closes. A cycle with no anomaly is recorded as
*clean*, which is positive evidence: the on-off rule needs clean cycles to see
an attacker go quiet.

**Signals to labels.** For a server, `classify_node` reads a window of cycles:

| Evidence in the window | Label |
|---|---|
| Lying signals (`latency_tell`, `cpu_honesty`) on most flagged cycles, rarely quiet | `sybil` |
| Lying signals, quiet for at least 20% of the active span in runs of 3+ clean cycles | `onoff` |
| Drop signals (`packet_drop`) with a median timeout rate of at least 0.85 | `blackhole` |
| Drop signals with a lower median rate, or a trust collapse with no measured rate | `grayhole` |
| Only `unreachable`, nothing else ever | `node_down`, a liveness failure rather than an attack |
| No flagged cycle | no opinion (abstain) |

Lying signals win over drop signals if they carry at least 25% of the cycles
that show either kind, because a CPU-burning liar also times tasks out. For a
device, `classify_client` names `spoof` or `bad_credentials` from an auth
denial (these latch: a denial stays true) and `flood` from the rate tell.
Every threshold is documented, with how it was derived, in
`attack_classifier.py`.

**Replay, not tally.** The scorer re-runs the classifier at every cycle over a
sliding window of the last 120 cycles, exactly as a live controller would.
That gives:

- a **run verdict**, the label the subject held for the most cycles. It is
  not the last label, because an on-off attacker is correctly abstained on in
  its quiet phases, and the last label would depend on where the run ended;
- a **detection latency**: the time of the first cycle with the correct label,
  minus the attack's onset (`attack_start_s`). Without an onset it is reported
  as unknown, never guessed.

**Scores.** Each subject is a hit (`OK`), a `FAMILY` hit (right kind of
attack, wrong sibling: sybil vs on-off, blackhole vs grayhole) or a `MISS`.
`none` is scored as a class like any other, so wrongly accusing an honest
server costs precision just as missing an attacker costs recall.

### Known limits

- **Simulated runs come from the simulator's own recording.** Since v0.2,
  `tests/scoring/conftest.py` scores the `events.jsonl` that `simulate` writes
  (see the Recording section of `docs/simulator.md`), so a change to what the
  simulator records shows up here.
- **The event fields are provisional.** The scorer follows the final-year
  project's `topology` shape (`graph.nodes`, `attack_start_s`). The project
  plan sketches a flatter one (`servers`, `start_s`). Whatever arj's schema
  settles on, only `ground_truth`, `onset_times` and `subject_aliases` read
  `topology`, so the change stays in those three functions.
- **Only two labels are exercised end to end.** The v0.1 simulator models a
  Sybil and an always-drop node, both hostile from second zero, so simulated
  runs only produce `sybil` and `blackhole` with an onset of 0. Grayhole,
  on-off, flood and spoof are covered by hand-built recordings until their
  attack profiles arrive in v0.3.
- **On a live testbed the latency is an upper bound.** Onset is counted from
  when an attacker's agent starts, but t0 is when the controller starts, a few
  seconds earlier. The report says so. In the simulator both clocks start
  together, so the latency is exact to the poll interval.
- **Magnitude needs evidence the defence denies.** A blackhole fails every
  task, so it is isolated fastest and leaves the fewest outcomes to measure.
  When there is no measured timeout rate the scorer says `grayhole`, the weaker
  claim, and the `FAMILY` column shows the family was still right.
