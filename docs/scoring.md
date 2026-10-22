# Scoring

**Owner:** arv · **Written in:** v0.2

## What it is

The scoring package converts simulation results into measurements that can be compared across load-balancing strategies. It covers non-functional requirements (NFR), availability, and metrics measured over fixed time intervals.

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

Attack scoring is maintained separately by its assigned owner.
