# The trust model

**Owner:** ash · **Written in:** v0.1

## What it is

`turncoat_sdn.trust` holds the decisions a Zero Trust controller makes about
its servers: how much to trust each one, which one gets the next task, and
when to cut one off. It was carved out of the final-year project and moved
without logic changes.

| Module | Holds | Ported from |
|---|---|---|
| `trust/calculator.py` | `TrustCalculator`, `TrustUpdate`, and `SimTrustModel` (new: the simulator hook) | `trust_engine/trust_calculator.py`, `contracts/trust_update.py` |
| `trust/edge_selector.py` | `EdgeWeights`, `NodeState`, `edge_score`, `is_quarantined`, `trust_band`, `select_edge_node` | `controller/edge_selector.py` |
| `trust/thresholds.py` | Isolation threshold 0.3, anomaly gate 0.5, rate-limit bands | `contracts/thresholds.py` |
| `trust/latency_tell.py` | The Sybil latency tell (moved by arj, see [Architecture](architecture.md)) | `controller/flow_monitor.py` |

[Concepts](concepts.md) explains the formula, EdgeScore and the two rails.
This page answers one question: **why can the formula not catch a liar on its
own?**

## Why it exists

The final-year project's trust formula is

```
T = 0.35·R + 0.25·B + 0.25·H − 0.15·A
```

and a server is isolated when `T < 0.3`. It looks as if dishonesty should
push a liar under the line: H measures how honestly a server reports its
load, and A rises when a detector flags it. It does not. A server that lies
about its load but still finishes its tasks quickly never falls below 0.44.

That finding is why the project added an anomaly gate that quarantines a
server on detector evidence alone, whatever its trust. It is also the reason
this benchmark exists: if our trust model had this blind spot and nobody
noticed for a semester, other trust models probably have blind spots too, and
the way to find them is a shared set of attackers and scorers.

## How to use it

Replay the liar against the real calculator. It finishes every task in
20 ms, claims a load of 0.05 while running at 0.95, and is flagged by the
anomaly detector on every single task:

```python
from turncoat_sdn.trust import NodeState, TrustCalculator, TrustUpdate, is_quarantined

lie = dict(cpu_usage=0.95, reported_cpu=0.05)  # runs at 0.95, claims 0.05

calc = TrustCalculator()
for _ in range(60):
    # Every task succeeds in 20 ms, and the detector flags every one.
    calc.update(TrustUpdate("iot1", "srv3", latency_ms=20.0, anomaly_flag=True, **lie))
print({k: round(v, 3) for k, v in calc.get_components("srv3").items()})
# {'R': 1.0, 'B': 0.96, 'H': 0.0, 'A': 1.0}
trust = calc.get_score("srv3")
print(round(trust, 3))
# 0.44

print(is_quarantined(NodeState("srv3", trust, cpu_load=0.05, latency_ms=20.0, anomaly=0.0)))
# False
print(is_quarantined(NodeState("srv3", trust, cpu_load=0.05, latency_ms=20.0, anomaly=0.85)))
# True
```

H is at its worst and A is at its worst, and trust still sits at 0.44. Only
the anomaly level, checked by the gate, removes the server.

The same thing happens inside the simulator. Pass `SimTrustModel` as the
`trust` hook. A round-robin router keeps feeding the Sybil its share of
tasks, so its trust is updated all run:

```python
import itertools

from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell


def round_robin(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


for tell in (None, latency_tell):
    run = simulate(round_robin, "sybil", seed=1000, trust=SimTrustModel, latency_tell=tell)
    print(run.time_to_isolate_s)
# None
# 3.0
```

With trust alone the Sybil is never isolated. With the latency tell feeding
the anomaly level, the gate isolates it on the third poll.

A router that wants the full Zero Trust decision builds a `NodeState` per
server from the four views the simulator passes to `choose`, then calls
`select_edge_node`. `tests/trust/conftest.py` has the `zt_sdn` and `no_trust`
routers from the final-year project written that way. arv's strategies task
moves them into `turncoat_sdn.strategies`.

## How it works inside

### The liar floor, step by step

Take a server that lies about its load but serves well. Push every term as
far against it as it can go:

| Term | Why it ends up there | Smoothed value | Weighted |
|---|---|---|---|
| R | Every task succeeds | 1.0 | 0.35 × 1.0 = 0.35 |
| B | Tasks finish in 20 ms: 1 − 20/500 | 0.96 | 0.25 × 0.96 = 0.24 |
| H | Claims 0.05, runs at 0.95: the gap is past 0.5 | 0.0 | 0.25 × 0.0 = 0.00 |
| A | Flagged on every task | 1.0 | − 0.15 × 1.0 = −0.15 |
| **T** | | | **0.44** |

Two of the four terms are about *service*, and the liar serves well, so they
stay high. Dishonesty can only zero out H (worth 0.25) and max out A (worth
−0.15), so the most a liar can lose to dishonesty is 0.40 of the 0.85 a
perfect server holds. That leaves 0.45, less the 0.01 that B gives up to 20 ms
of latency: 0.44, above 0.3 no matter how blatant the lie.

On the way down from the starting score the liar stays above the line too:
`test_the_liar_never_crosses_the_isolation_threshold` checks every step, not
just the end.

### The dropper has the same blind spot

A server that silently drops every task but reports its load honestly ends at

```
T = 0.35·0.3 + 0.25·0.0 + 0.25·1.0 − 0.15·0.0 = 0.355
```

R falls only to 0.3, because the calculator scores a timeout at 0.3 rather
than 0, and H stays at 1 because the server is honest about its load. So trust
alone does not isolate it either until a detector flags it. In the simulator
the timeout-rate tell does that, and once A rises the dropper's trust falls to
about 0.2.

### What the simulator shows

Run the Sybil scenario under round-robin over seeds 1000 to 1009 and watch
the Sybil's trust at every routing decision:

| Anomaly evidence | Decisions where the Sybil's trust was below 0.3 |
|---|---|
| None (no latency tell) | 0% on every seed |
| Latency tell feeding A | 29% to 55%, depending on the seed |

Without evidence the score never isolates the Sybil, which is the floor at
work. With evidence the score dips under the line only part of the time. The
simulated Sybil is slowed by its own CPU burn, so its B term wobbles with its
queue. A score that crosses the line on and off would quarantine and readmit
the server over and over. The anomaly level, once it reaches the gate, stays
at or above it for the rest of the run on all ten seeds, so the gate holds the
Sybil out steadily.

### Proof that the port is faithful

| Test | Checks |
|---|---|
| `tests/trust/test_calculator.py` | T-01 to T-07 from the project's `test_trust.py`, and that `SimTrustModel` scores a simulator outcome exactly as `evaluation/baseline.py` did |
| `tests/trust/test_edge_selector.py` | The project's `test_edge_selector.py` and the band tests from `test_graduated_response.py`, and that `SimConfig`'s copies of the thresholds match |
| `tests/trust/test_liar_floor.py` | The 0.44 floor against the real calculator, the project's F-04 liar test, the 0.355 dropper floor, and the floor inside a simulated run |
| `tests/trust/test_zt_sdn.py` | `no_trust` and `zt_sdn` reproduce the original `evaluation/baseline.py` numbers to the last digit on every scenario (`golden_fyp_edge_score.json`), plus detection tests E-08 to E-11 |

## Known limits

- **The floor is about a liar that stays fast.** The simulator's built-in
  Sybil doubles its service time, so it is a degrading liar and its trust does
  dip below 0.3 once a detector flags it. A liar that burns no visible latency
  is the harder case. It needs an attack profile of its own, which fits the v0.3
  attack interface.
- **Weights are checked with `assert`.** `TrustCalculator` rejects weights
  that do not sum to 1.0 with an `AssertionError`, as in the original. Under
  `python -O` the check disappears.
- **`select_edge_node` keeps some global state.** Exact ties under `argmax`
  are broken by a module-level round-robin counter, and if no `rng` is passed
  it draws from the global `random` module. Benchmark runs use `p2c` with a
  seeded `rng`, so neither affects them, but call it with an explicit `rng`.
- **Only the pure decisions moved.** The live controller's `TrustState`
  (probation, evidence ageing, the busy-time honesty check and the score-only
  ablation switch) and the OpenFlow meters for rate limiting stay in the
  final-year project.
