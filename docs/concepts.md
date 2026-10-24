# Concepts

**Owner:** ash · **Written in:** v0.1

## What it is

The handful of ideas everything else in turncoat-sdn is built on: the trust
score, EdgeScore, the isolation threshold and the anomaly gate, ground truth,
and paired comparison. Each one is a few lines of code in
`turncoat_sdn.trust` or `turncoat_sdn.sim`, and this page says what that code
does in plain words.

## Why it exists

Every other page assumes you know these terms. A scorer that reports "the
grayhole was quarantined 14 s after onset" only makes sense once you know what
quarantine is, what decides it, and how the benchmark knows when the attack
began. Read this page before picking up a task.

## How to use it

The trust model and the selector are plain Python, so you can try every idea
here without a simulator. Two nodes report ten task outcomes each: `srv1`
finishes every task in 40 ms, `srv2` times out every task. A third node,
`srv3`, has been flagged by an anomaly detector.

```python
from turncoat_sdn.trust import (
    EdgeWeights,
    NodeState,
    TrustCalculator,
    TrustUpdate,
    select_edge_node,
    trust_band,
)

served = dict(task_status="success", cpu_usage=0.3, reported_cpu=0.3, latency_ms=40.0)
dropped = dict(task_status="timeout", cpu_usage=0.5, reported_cpu=0.5, latency_ms=2000.0)

calc = TrustCalculator()
for _ in range(10):
    calc.update(TrustUpdate("iot1", "srv1", **served))
    calc.update(TrustUpdate("iot1", "srv2", **dropped))
print({n: round(t, 3) for n, t in calc.get_all_scores().items()})
# {'srv1': 0.83, 'srv2': 0.355}

fleet = [
    NodeState("srv1", trust=calc.get_score("srv1"), cpu_load=0.30, latency_ms=50.0),
    NodeState("srv2", trust=calc.get_score("srv2"), cpu_load=0.10, latency_ms=50.0),
    NodeState("srv3", trust=0.80, cpu_load=0.05, latency_ms=50.0, anomaly=0.85),
]
for s in fleet:
    print(s.node_id, trust_band(s))
# srv1 full
# srv2 rate_limited
# srv3 quarantined

chosen, score, ranked = select_edge_node(fleet, EdgeWeights())
print(chosen, round(score, 3), [(n, round(x, 3)) for n, x in ranked])
# srv1 0.625 [('srv1', 0.625), ('srv2', 0.448)]
```

`srv3` claims the lowest load and has good trust, but it never reaches the
ranking: the anomaly gate removed it first. `srv2` claims less load than
`srv1` but loses on trust.

## How it works inside

### Trust score

Each server gets a score `T` between 0 and 1, built from four signals. Every
finished task updates all four, for the server that ran it:

| Signal | Weight | Raw value from one task | Code |
|---|---|---|---|
| R, reputation | α = 0.35 | 1.0 on success, 0.3 on timeout, 0.0 on failure | `_STATUS_MAP` |
| B, behavioural consistency | β = 0.25 | `1 − latency_ms / 500`, floored at 0 | `b_raw` |
| H, resource honesty | γ = 0.25 | `1 − abs(reported_cpu − actual_cpu) / 0.5`, floored at 0 | `h_raw` |
| A, attack suspicion | δ = 0.15 | 1.0 if the anomaly flag was set, else 0.0 | `a_raw` |

```
T = 0.35·R + 0.25·B + 0.25·H − 0.15·A        clipped to [0, 1]
```

Each signal is an exponential moving average, `X ← λ·x + (1 − λ)·X`, with
λ = 0.85. λ is the weight of the *newest* task, so the score follows a node
within two or three tasks rather than drifting slowly. A node that has never
reported starts at 0.5 on R, B and H and 0 on A, so its first score is 0.5.

The best possible score is 0.85 (R = B = H = 1, A = 0), not 1.0. The weights
must sum to 1.0, and the calculator refuses any that do not.

`TrustCalculator` is the calculator from the final-year project, unchanged.
`SimTrustModel` wraps it so the simulator can call it once per finished task
(see [The trust model](trust-model.md)).

### EdgeScore

When a task arrives, the controller ranks every server it may use:

```
EdgeScore(n) = 0.50·T(n) + 0.30·(1 − cpu(n)) + 0.20·(1 − latency(n) / max_latency)
```

A server must be both trusted and not busy to win. Two details matter:

- **`cpu` is what the server claims**, not what it really carries. A liar's
  claim of being idle is exactly what makes it attractive, and that is the
  attack the benchmark has to be able to show.
- **Latency is normalised over the eligible servers only**, so a quarantined
  server's slow replies do not change anyone else's score.

`select_edge_node` picks the winner. By default it takes the highest score
(`argmax`). The `zt_sdn` strategy uses *power of two choices* instead: it
samples two eligible servers at random and takes the better one, and with
probability ε = 0.05 it picks any eligible server at random. Without that, the
top two or three servers win every task and the rest starve.

### Isolation threshold and anomaly gate

Before any ranking, a server is **quarantined** (removed from the candidates)
if either rail trips:

- its trust falls **below 0.3**, the isolation threshold, or
- its smoothed anomaly level reaches **0.5**, the anomaly gate, whatever its
  trust.

The anomaly level comes from detectors that do not depend on trust. In the
simulator these are the latency tell, which catches a server claiming to be
idle while answering slowly, and the timeout-rate tell, which catches a server
whose tasks stop coming back. Each poll turns their verdicts into a raw flag
of 0 or 1, smoothed with an EMA of the same 0.85, so a single poll on which a
detector trips already reaches the gate.

The gate exists because trust alone cannot catch a competent liar. A server
that lies about its load but still finishes tasks quickly settles at T = 0.44,
above the 0.3 line, even with every dishonesty signal at its worst.
[The trust model](trust-model.md) works through why.

If every server is quarantined, selection returns `None` and the task is
**denied**. The system never falls back to an untrusted server.

Between full service and quarantine there is a middle band. A server with
trust in [0.3, 0.5) or anomaly in [0.25, 0.5) is **rate-limited**: in the
live testbed it still gets traffic, through an OpenFlow meter. `trust_band`
reports which band a server is in.

| Band | Trust | Anomaly |
|---|---|---|
| `full` | ≥ 0.5 | < 0.25 |
| `rate_limited` | 0.3 to 0.5, or | 0.25 to 0.5 |
| `quarantined` | < 0.3, or | ≥ 0.5 |

### Ground truth

The simulator knows which server is an attacker, because it made it one.
`malicious_roles("both", 8)` returns `{7: 'sybil', 6: 'drop'}`: servers
`srv8` and `srv7`. Today the simulator uses this to measure
`time_to_isolate_s`, the first moment every attacker is excluded from routing.

From v0.2 the same knowledge is written into the first event of every
recording, with each attacker's onset time from v0.3. A scorer can then say
"the system caught the grayhole 14 seconds after onset" rather than only
"the system quarantined srv3".

### Paired comparison

Every strategy runs on the same seeds. Run 7 of `zt_sdn` and run 7 of
`least_conn` face the identical stream of tasks with identical service times,
so the difference between them is the routing and nothing else. Comparing
pairs removes most of the noise, which is why the statistics use a Wilcoxon
signed-rank test. [The simulator](simulator.md) explains how the seeds are
split so the pairing holds.

### Turncoat and onset

A **turncoat** behaves honestly at first, earns trust, then turns hostile at
its onset time, `start_s`. An attacker that is hostile from second zero is
easy to catch. One that has already earned a high score is the real test.

## Known limits

- **Onset defaults to zero.** The built-in scenarios' attackers are hostile
  from the first second unless `SimConfig(attack_start_s=...)` delays them, so
  existing results stay comparable. [Attacks](attacks.md) shows how to set an
  onset per attacker.
- **The middle band is not simulated.** `trust_band` classifies nodes, but the
  simulator only distinguishes routable from quarantined. Rate limiting needs
  the live testbed's OpenFlow meters.
- **No way back from quarantine in the simulator.** A quarantined node gets no
  tasks, so its trust stops changing. The live controller offered probation
  tasks to win trust back; that logic belongs to its `TrustState` and was not
  moved.
- **The signal names differ from the project plan.** The plan's summary calls
  B "honest behaviour" and H "history". In the calculator, B measures latency
  and H measures the honesty of the load report. This page follows the code.
