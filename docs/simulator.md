# The simulator

**Owner:** bv · **Written in:** v0.1 · **Extended in:** v0.2 (recording to `events.jsonl`)

## What it is

`turncoat_sdn.sim` is a seeded discrete-event model of an edge farm: a fleet
of servers, a Poisson stream of IoT tasks, a controller that polls every node
for its load and round-trip time, and up to two attackers. You give it a
routing strategy, a scenario and a seed. It returns a `RunResult` with the
SLO violation rate, failure rate, the share of traffic the attackers received,
latency, fairness and how long it took to isolate every attacker.

It needs nothing but the Python standard library. It never imports os-ken,
Ryu or Mininet, and it does not import the other turncoat subpackages either:
routing, trust and the latency tell are passed in as hooks.

## Why it exists

Comparing five strategies on four scenarios over 30 seeds is 600 runs. That
takes minutes here and would take days on a live Mininet topology. A
statistical claim needs that many repetitions, so the simulator is what makes
the comparison possible at all.

It is a port of `evaluation/baseline.py` from our final-year project, and it
produces the same numbers to the last rounded digit (see
[Fidelity](#fidelity-to-the-final-year-project)). The live testbed stays the
reference for realism; the simulator is the reference for statistics.

## How to use it

A run needs a **router factory**: a callable that takes the node count and a
seeded `random.Random`, and returns an object with a `choose` method.

```python
import itertools

from turncoat_sdn.sim import simulate


def round_robin(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


run = simulate(round_robin, "drop", seed=1000)
print(
    f"{run.slo_violation_rate:.4f} SLO violations, "
    f"{run.malicious_share:.3f} of tasks sent to the dropper"
)
# 0.1944 SLO violations, 0.125 of tasks sent to the dropper
```

To compare strategies, use `run_paired`. It runs every strategy on every
scenario with the same seeds, and `write_csv` saves one row per run:

```python
from turncoat_sdn.sim import run_paired, write_csv

results = run_paired({"round_robin": round_robin}, seeds=range(1000, 1030))
write_csv(results, "runs.csv")
```

Change the fleet, the workload or the attackers with `SimConfig`:

```python
from dataclasses import replace

from turncoat_sdn.sim import SimConfig, simulate

small = replace(SimConfig(), n_nodes=4, sim_s=60.0)
run = simulate(round_robin, "both", seed=7, config=small)
```

From v0.2 the `turncoat run` command wraps all of this, using the strategies
in `turncoat_sdn.strategies`.

### Scenarios

| Scenario | Attackers | What it tests |
|---|---|---|
| `clean` | none | A defence must cost nothing when there is no threat. |
| `sybil` | last node lies, claiming 10% load while serving at half speed | It never fails a task, so trust alone cannot catch it. Only the latency tell can. |
| `drop` | last node accepts tasks and never finishes them | Its tasks time out, so the timeout-rate tell catches it. |
| `both` | the Sybil on the last node, the dropper on the one before | Both at once. |

Attackers sit at the end of the index range so a round-robin never starts on
one. In v0.3 these fixed scenarios become attack profiles with an onset time
`start_s`.

### Hooks

`simulate` takes three hooks. Only the router is required.

| Hook | Shape | Without it |
|---|---|---|
| `router` | `factory(n, rng)` returning an object with `choose(trust, claimed_cpu, rtt_ms, anomaly) -> int or None` | required |
| `trust` | `factory()` returning an object with `initial_score` and `update(outcome) -> float` | every node keeps trust 1.0 |
| `latency_tell` | an object or module with `fleet_latency_baseline(rtts)` and `evaluate_latency_tell(claimed_cpu, measured_rtt_ms, fleet_baseline_ms, strikes)` | the Sybil is never flagged |

The exact signatures are the protocols in `turncoat_sdn/sim/hooks.py`. The
trust model receives an `Outcome` whose fields match the project's
`TrustUpdate`, and the latency-tell functions moved out of `flow_monitor.py`
fit the `latency_tell` hook as they are.

A router returns `None` to refuse a task when every node is quarantined. The
task then counts as both a failure and an SLO violation, so isolating the
whole fleet is never free.

### What a run measures

| Field | Meaning |
|---|---|
| `slo_violation_rate` | Fraction of offered tasks that failed or took longer than `slo_ms` (500 ms). The primary outcome: both attacks move it. |
| `failure_rate` | Fraction that timed out, gave up in a backlog, or were refused. |
| `malicious_share` | Fraction routed to an attacker. |
| `mean_latency_ms`, `p95_latency_ms` | Over completed tasks only. |
| `gini` | Inequality of tasks per node: 0 is perfectly even. |
| `time_to_isolate_s` | First poll at which every attacker was below the isolation threshold or at the anomaly gate. Empty when that never happened. |

## How it works inside

### The model

Each node is an M/M/c queue with `concurrency` (4) workers and a FIFO backlog.
Honest service times are exponential with a 0.2 s mean. Tasks arrive as a
Poisson stream at `load_factor` (40%) of the farm's capacity. A client gives
up after `task_timeout_s` (2 s), and a task that waited longer than that in a
backlog is counted as failed when a worker finally reaches it.

The event loop pops four kinds of event from a heap, in time order:

- **arrival:** draw the task's service demand, ask the router for a node, and
  start the task or queue it.
- **completion** or **timeout:** record the latency, free the worker, pull
  from the backlog, and pass the outcome to the trust model.
- **poll** (every `poll_s`, 1 s): refresh every node's claimed load and RTT,
  run the latency tell and the timeout-rate tell, smooth them into each node's
  anomaly level, and check whether every attacker is now excluded.

The controller only learns a node's load at each poll. Between polls every
arrival is routed on the same stale snapshot, which is why load-aware
strategies herd. That is a real result, not a bug: see
[Known limits](#known-limits).

### Why seeds are paired

A comparison between two strategies is only fair if they faced the same
conditions. So run *k* of every strategy uses the same seed, and the seed
fixes everything except the routing decision.

The simulator keeps four independent random streams per run:

| Stream | Seed | Drives |
|---|---|---|
| arrivals | `seed` | gaps between tasks |
| service | `seed + 17` | each task's service demand |
| jitter | `seed + 43` | RTT noise at each poll |
| selection | `seed + 99` | the router's own choices |

If all draws came from one stream, the strategies would consume it in a
different order as soon as they made different choices, and the k-th task
would get a different service demand under each one. With separate streams
the k-th task is the same task for everyone: the technique is called common
random numbers. Because the samples are matched, the paired Wilcoxon
signed-rank test in `turncoat_sdn.stats` applies, and it removes most of the
run-to-run noise.

`tests/sim/test_simulator.py` checks this property: one seed gives every
strategy the same number of offered tasks.

### Fidelity to the final-year project

`tests/sim/golden_fyp_baseline.json` holds 24 rows produced by the original
`evaluation/baseline.py`: three trust-blind strategies on all four scenarios
for two seeds. `tests/sim/test_golden.py` reruns them through the port and
requires every field to match. If it fails, the port is wrong; never edit the
expected numbers.

While porting, we also ran the original and the port side by side with the
real trust calculator, edge selector and latency tell plugged into the hooks.
All 100 runs (five strategies, four scenarios, five seeds) matched on every
field, including `time_to_isolate_s`. That check will become a permanent test
once `turncoat_sdn.trust` and `turncoat_sdn.strategies` land.

## Known limits

- **It is a model.** The network, the node agents and the clients are
  simulated. Only the decisions plugged into the hooks are real code.
- **Load staleness is built in.** Load-aware strategies pay for the 1 s poll
  in the clean scenario; the final-year project measured `zt_sdn` at 0.091
  against round-robin's 0.083. Shortening `poll_s` removes the gap.
- **Small fleets hit a capacity cliff.** With 4 nodes in `both`, quarantining
  two leaves the other two at 80% utilisation, and queueing eats the gain from
  isolation. The default of 8 nodes avoids this; results at 4 nodes measure the
  cliff, not the strategy.
- **Fixed attackers.** v0.1 has the four built-in scenarios only, with
  attackers hostile from the start. Delayed onset and the full attack catalogue
  arrive in v0.3.
- **No recording yet.** Runs return metrics, not an event stream. Writing
  `events.jsonl` arrives in v0.2.
- **The optimiser strategy was not ported.** The project's `zt_sdn_rf`
  (EdgeScore weights chosen by a UCB1 bandit) is outside the benchmark's five
  strategies.
