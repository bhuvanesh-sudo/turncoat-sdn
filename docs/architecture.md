# Architecture

**Owner:** arj · **Written in:** v0.1

## What it is

A map of the `turncoat_sdn` package: what each subpackage holds, which ones
may import which, and the one rule that keeps the core runnable on a plain
laptop. Read it before adding a module, so you know where the module goes and
what it is allowed to depend on.

## Why it exists

The final-year project was built around a live os-ken controller, and the SDN
stack reached places it did not belong. The offline evaluation harness,
`evaluation/baseline.py`, never touched a switch. It still could not run
without os-ken, because it imported two pure functions from
`controller/flow_monitor.py`, and that file starts with
`from os_ken.lib import hub`.

That is the kind of tangle this page exists to prevent. A benchmark that
needs an SDN controller just to import is a benchmark nobody runs, so the
dependency rules below are written down, and the tests enforce them.

## How to use it

Before you add code, find its row in the [package map](#package-map) and check
the [dependency rules](#dependency-rules). If the code needs os-ken, Ryu or
Mininet, it goes under `backends/`, never under `src/turncoat_sdn/`.

The pieces fit together through plain function calls. The simulator takes
its controller decisions as hooks, and a module from another subpackage can
fill a hook directly. Here the latency tell from `trust` catches the Sybil
inside a `sim` run:

```python
import itertools

from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import latency_tell


def round_robin(n, rng):
    cycle = itertools.cycle(range(n))

    class RoundRobin:
        def choose(self, trust, claimed_cpu, rtt_ms, anomaly):
            return next(cycle)

    return RoundRobin()


blind = simulate(round_robin, "sybil", seed=1000)
told = simulate(round_robin, "sybil", seed=1000, latency_tell=latency_tell)
print(blind.time_to_isolate_s, told.time_to_isolate_s)
# None 3.0
```

Without the tell the Sybil is never isolated. With it, the Sybil is flagged
on the third poll, as in the final-year project.

To check that your change keeps the core clean, run the same checks as CI:

```bash
pytest tests/test_package.py   # imports every core module, looks for os-ken
ruff check .                   # rejects a direct os-ken, Ryu or Mininet import
python -c "import turncoat_sdn"
```

## How it works inside

### Package map

| Subpackage | Holds | Owner | Status | Ported from (final-year project) |
|---|---|---|---|---|
| `sim/` | Seeded discrete-event simulator, scenarios, run metrics, hook protocols | bv | v0.1 | `evaluation/baseline.py` |
| `trust/` | Latency tell | arj | v0.1 | `controller/flow_monitor.py` (two functions only) |
| `trust/` | Trust calculator, edge selector, thresholds, anomaly gate | ash | v0.1 | `trust_engine/trust_calculator.py`, `contracts/trust_update.py`, `controller/edge_selector.py`, `contracts/thresholds.py` |
| `strategies/` | `random`, `round_robin`, `least_conn`, `no_trust`, `zt_sdn` behind one interface | arv | planned, v0.1 | `evaluation/baseline.py` |
| `events/` | Event schema 1.0, JSONL writer and reader, validator (see `event-format.md`) | arj | v0.2 | `controller/event_bus.py` (JSONL part), `evaluation/nfr_report.load_events` |
| `scoring/` | Attack classifier and attack scorer | ash | v0.2 | `controller/attack_classifier.py`, `evaluation/attack_report.py` |
| `scoring/` | NFR, interval and availability scorers | arv | planned, v0.2 | `evaluation/nfr_report.py`, `interval_report.py`, `availability_report.py` |
| `attacks/` | One profile per attack, each with a `start_s` onset | ash and everyone | planned, v0.3 | `simulation/attack_simulator.py` |
| `stats/` | Paired Wilcoxon with Holm, bootstrap CIs, replicate aggregator | arv, bv, arj | planned, v0.4 | `evaluation/stats.py` |
| `cli.py` | The `turncoat` command | jv | entry point now, commands from v0.2 | — |
| `backends/mininet/` | Optional live testbed (outside the core package) | bv | planned, v1.0 | `simulation/node_agent.py`, `iot_client.py`, `topology.py` |

### Dependency rules

Arrows point from a package to the packages it may import. Nothing imports
upward, and nothing in the core imports a backend.

```
                 cli.py
                   |
     +-------------+--------------+
     v             v              v
   stats  ---->  scoring  ---->  events
                   |
                   v
 strategies --> trust            sim   <-- hooks filled by trust and strategies
                                          (the caller passes them in;
     attacks                              sim imports neither)

 backends/mininet  --> may import any core package, plus os-ken and Mininet
```

1. **The core never imports the SDN stack.** No module under
   `src/turncoat_sdn/` imports `os_ken`, `ryu` or `mininet`, directly or
   through another module.
2. **`sim` imports nothing else from `turncoat_sdn`.** Routing, trust and the
   latency tell are hooks, declared as protocols in `sim/hooks.py`, so the
   simulator can be tested on its own with stand-in hooks. The caller (a test,
   and from v0.2 the CLI) joins the pieces together.
3. **Shared logic has one home.** When the live controller and the simulator
   need the same decision, it lives in a pure function in the core, and both
   call it. The latency tell is the first example: the live monitor and the
   simulator called one copy in the final-year project, and when the Mininet
   backend lands in v1.0 it imports the same function from `trust`.
4. **Data flows one way after a run.** From v0.2, runs produce `events.jsonl`,
   `scoring` reads it, and `stats` reads scores. Nothing upstream depends on
   anything downstream.

### What moved for v0.1, and why

| Function | Was in | Now in | Why it moved |
|---|---|---|---|
| `fleet_latency_baseline` | `controller/flow_monitor.py` | `trust/latency_tell.py` | A pure median over probe RTTs, stuck in a module that imports `os_ken.lib.hub` |
| `evaluate_latency_tell` | `controller/flow_monitor.py` | `trust/latency_tell.py` | The load-independent Sybil tell, a pure function, same problem |
| `TrustCalculator`, `TrustUpdate` | `trust_engine/trust_calculator.py`, `contracts/trust_update.py` | `trust/calculator.py` | The trust formula `zt_sdn` routes on; `SimTrustModel` beside it fills the simulator's trust hook |
| `select_edge_node` and friends | `controller/edge_selector.py` | `trust/edge_selector.py` | EdgeScore and quarantine, shared by the `no_trust` and `zt_sdn` strategies |
| Isolation threshold, anomaly gate, bands | `contracts/thresholds.py` | `trust/thresholds.py` | The two rails every quarantine decision and scorer depends on |

Both functions moved without logic changes: same arguments, same defaults,
same leaky-bucket persistence. The result tuple is now `LatencyTellResult`
rather than `LatencyTell`, because `turncoat_sdn.sim.LatencyTell` already
names the hook protocol the module satisfies. The rest of `flow_monitor.py`
(the `/status` poll loop, per-hardware-class baselines and the attack
classifier wiring) is live-controller code and stays out of the core.

`tests/trust/test_latency_tell.py` replays the scenarios from the project's
`test_flow_monitor.py` against the moved functions. It also checks that
plugging the module into the simulator gives the same `time_to_isolate_s`
as the original golden numbers.

### How the rules are enforced

| Check | Catches | Where |
|---|---|---|
| Ruff `TID251` banned imports | A direct `import os_ken`, `ryu` or `mininet` in the core | `pyproject.toml`, every CI lint run |
| `test_core_does_not_import_sdn_stack` | Any core module that pulls the SDN stack in, even through another module | `tests/test_package.py`, imports every module in a fresh interpreter |
| CI "Confirm the SDN stack is absent" | A runner that has os-ken installed and would hide a leak | `.github/workflows/ci.yml` |

## Known limits

- **Rules 2 to 4 are conventions, not checks.** Only rule 1 is enforced
  automatically. A reviewer has to catch an upward import, such as `events`
  importing `scoring`.
- **Most of the map is a plan.** Rows marked *planned* follow the project
  plan and may shift when the code lands. The owner of each move should update
  this page in the same pull request.
- **The fleet baseline assumes a uniform fleet.** `fleet_latency_baseline` is
  a median over every node. On mixed hardware, an honest but slower class
  (Raspberry Pis among NUCs) looks like a liar. The live monitor solved this
  with per-class baselines, which were not moved, because the simulator's
  fleet is uniform. A test records this limit.
