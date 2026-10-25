# Extending the benchmark

**Owner:** arj · **Written in:** v1.0 · Custom attack section by ash

## What it is

How to plug your own work into turncoat-sdn: a new attack, a new
load-balancing strategy, or a whole outside system that writes the shared
event format. Each comes with a runnable example in [`examples/`](../examples/)
that CI runs on every change, so the code on this page cannot quietly go
stale.

| You have | You write | Example | Section |
|---|---|---|---|
| A new way for a node to turn | A `ServerAttack` or `ClientAttack` subclass | `examples/custom_attack.py` | [Your own attack](#your-own-attack) |
| A new way to route tasks | A router factory | `examples/custom_strategy.py` | [Your own strategy](#your-own-strategy) |
| A system of your own | An `events.jsonl` recording | `examples/score_outside_recording.py` | [Your own system](#your-own-system) |

## Why it exists

A benchmark is only worth something if it can test what its authors did not
think of. The attacks, strategies and scorers here are the ones the
final-year project needed. Yours will differ, and the point of a shared event
format and paired seeds is that your attack faces the same workload as ours,
and your system is graded by the same scorers.

## Your own attack

A new turncoat takes one small class. The base class keeps the server honest
until its onset, so the class only says what changes once it turns.
[`examples/custom_attack.py`](../examples/custom_attack.py) builds one,
runs it, scores it and tests the result over paired seeds, in 48 lines of
code.

### 1. Write the attack

The *slowpoke* serves every task it accepts, but four times slower, and
reports its load honestly. It drops nothing and tells no lie:

```python
from turncoat_sdn.attacks import ServerAttack


class Slowpoke(ServerAttack):
    """Serves every task ``slowdown`` times slower from ``start_s`` on, and never lies."""

    name = "slowpoke"  # the ground-truth label written into the recording

    def __init__(self, start_s: float = 0.0, *, slowdown: float = 4.0) -> None:
        super().__init__(start_s)
        self.slowdown = slowdown

    def serve(self, now, demand_s, rng):
        return demand_s * self.slowdown  # late, but it answers
```

`serve` decides how long an accepted task holds a worker, or returns `None`
to drop it. `report` (not overridden here) decides what the server claims at
each controller poll. Both are called only after `start_s`. The full
interface, including attacks by IoT clients, is in
[attacks.md](attacks.md#how-to-write-an-attack).

### 2. Place it and run it

Hand it to the simulator by node index. Node 7 is `srv8`, and one instance
can serve every run:

```python
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventList
from turncoat_sdn.sim import simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

recording = EventList(backend="sim", seed=1, strategy="zt_sdn", scenario="slowpoke")
hooks = {"trust": SimTrustModel, "latency_tell": latency_tell, "recorder": recording}
simulate(STRATEGIES["zt_sdn"], "clean", 1, attacks={7: Slowpoke(start_s=30.0)}, **hooks)
```

`"clean"` supplies an honest fleet; `attacks` places yours in it. Pass
`attacks={}` on the same seed for the honest run to pair it with: same
arrivals, same service demands, so the only difference is your attack. Your
attack's `rng` is its own seeded stream and never shifts that workload.

### 3. Score it

The recording carries your attack's name and onset as ground truth, so the
same scorers grade it as any built-in attack. In Python,
`turncoat_sdn.cli.score.score_recording(recording.events)` returns what
`turncoat score --json` prints. Or write the run to a file and use the
command line:

```bash
python examples/custom_attack.py --record slowpoke.jsonl
turncoat validate slowpoke.jsonl
turncoat score slowpoke.jsonl
```

```
Attackers
  srv8     slowpoke   missed as none
           detected never after onset
           never flagged for quarantine
```

### 4. Ask whether it matters

One seed is an anecdote. The example runs every seed twice, honest and with
the slowpoke, and tests the paired SLO violation rates with
`turncoat_sdn.stats.paired_wilcoxon`:

```
$ python examples/custom_attack.py
Slowpoke on srv8 from 30 s, 10 paired seeds

  zt_sdn      SLO violations  9.26% -> 12.66%  (Wilcoxon p = 0.0020); quarantined in 0 of 10 runs
  least_conn  SLO violations 17.39% -> 23.79%  (Wilcoxon p = 0.0020); quarantined in 0 of 10 runs
```

The slowpoke made things worse on all ten seeds, and no strategy quarantined
it once. That is a finding, not a broken example. The trust score is built
from task success and honest reporting, and the slowpoke fails almost
nothing (only the odd long task now outlasts the client's timeout) and never
lies. The latency tell looks for a server whose poll answers are slow for the
load it claims, and the slowpoke's claims are true. What limits the damage is
that honesty: a busy slowpoke reports busy, so EdgeScore and `least_conn`
send it less work than `round_robin` would. Every task it does serve,
though, takes about 0.8 s against a 500 ms deadline.

`missed as none` is the right verdict too. The attack classifier has no rule
for a slow but honest server, so no label could be right. When your attack
belongs to a known family, name it after that family (`grayhole`, `onoff`,
and the rest in [attacks.md](attacks.md#how-to-write-an-attack)) and the
scorer will check the classifier's verdict against it.

### Rules your attack must follow

- **Draw randomness only from `rng`.** Never the global `random` module, or
  your attack stops being reproducible and can shift the paired workload.
- **Keep no per-run state on the instance.** One instance may serve many
  runs. Work out anything time-dependent from `now`.
- **Don't override `service_time` or `status`.** They apply the onset and
  then call `serve` and `report`.

`tests/examples/test_custom_attack.py` checks the example against these,
runs it as a script, and fails if it grows past 50 lines of code.

### Into the catalogue

Run this way, your attack works from Python only. To make it a built-in
scenario that `turncoat run --scenario`, `turncoat replicate` and
`turncoat compare` can use, follow
[Adding one to the catalogue](attacks.md#adding-one-to-the-catalogue).

## Your own strategy

A strategy decides which server gets each task. The simulator takes it as a
**router factory**: a function `factory(n, rng)` that it calls once per run
with the number of servers and the run's own seeded random stream, and that
returns an object with one method. The five built-in strategies are factories
of exactly this shape, in `turncoat_sdn.cli.routers.STRATEGIES`.

### 1. Write the strategy

[`examples/custom_strategy.py`](../examples/custom_strategy.py) writes one in
49 lines of code. *Gated round robin* keeps round robin's strict cycle, but
skips any server that the trust floor or the anomaly gate holds out, the two
rails `zt_sdn` quarantines with:

```python
from turncoat_sdn import trust

FLOOR, GATE = trust.DEFAULT_ISOLATION_THRESHOLD, trust.DEFAULT_ANOMALY_GATE


def gated_round_robin(n, rng):
    class GatedRoundRobin:
        cursor = 0

        def choose(self, scores, claimed_cpu, rtt_ms, anomaly):
            for k in range(n):
                i = (self.cursor + k) % n
                if scores[i] >= FLOOR and anomaly[i] < GATE:
                    self.cursor = i + 1
                    return i

    return GatedRoundRobin()
```

`choose` sees the controller's view at the moment a task arrives, one value
per server: trust score, claimed load (0 to 1), measured poll RTT in
milliseconds, and smoothed anomaly level (0 to 1). It returns the index of
the chosen server, or `None` to refuse the task, which counts as a failure.
Here `None` comes from falling off the end of the loop when every server is
held out. The exact protocol is `turncoat_sdn.sim.Router`.

### 2. Run it

Pass the factory to the simulator exactly as a built-in strategy is passed,
with the same trust model and latency tell, so it sees the controller view
every other strategy sees:

```python
from turncoat_sdn.events import EventList
from turncoat_sdn.sim import simulate

recording = EventList(backend="sim", seed=1, strategy="gated_rr", scenario="both")
hooks = {"trust": trust.SimTrustModel, "latency_tell": trust.latency_tell, "recorder": recording}
simulate(gated_round_robin, "both", 1, name="gated_rr", **hooks)
```

The same seed gives your strategy the same arrivals, service demands and
attackers as every built-in one, so runs pair seed by seed. Score each
recording with `turncoat_sdn.cli.score.score_recording`, as for an attack.

### 3. Compare it

The example runs it against `zt_sdn` and `round_robin` on 10 paired seeds of
`both` (a Sybil and a blackhole) and tests every gap with
`turncoat_sdn.stats.paired_wilcoxon`:

```
$ python examples/custom_strategy.py
gated_rr against two built-ins on 'both' (a Sybil and a blackhole), 10 seeds

  slo_violation_rate  gated_rr  8.95%  vs  zt_sdn      12.37%  (Wilcoxon p = 0.0020)
  slo_violation_rate  gated_rr  8.95%  vs  round_robin 23.61%  (Wilcoxon p = 0.0020)
  failure_rate        gated_rr  0.30%  vs  zt_sdn       0.09%  (Wilcoxon p = 0.0020)
  failure_rate        gated_rr  0.30%  vs  round_robin 12.09%  (Wilcoxon p = 0.0020)
```

With 10 pairs, p = 0.0020 is the smallest a two-sided Wilcoxon test can give:
every one of the ten seeds went the same way. The gates alone remove almost
every failure that plain round robin suffers, because a quarantined attacker
gets no more tasks. More surprising, the gated cycle has fewer SLO violations
than `zt_sdn` on every seed, and more failures. A likely reason for the first
is the load staleness described in
[simulator.md](simulator.md#known-limits): `zt_sdn` weighs the load each
server reported at the last poll, so between polls it keeps favouring the
server that looked idlest, while the cycle spreads work evenly. A likely
reason for the second is that EdgeScore already steers away from a server
whose trust is falling, before the gate closes, while the cycle keeps
sending it its turn. Whichever it is, it is a question this benchmark can
now ask.

`python examples/custom_strategy.py --record gated.jsonl` also writes one
run to a file for `turncoat validate` and `turncoat score`.

### Rules your strategy must follow

- **Draw randomness only from `rng`.** It is the run's own selection stream;
  anything else breaks pairing across strategies.
- **Keep per-run state on the router object**, not at module level. The
  factory is called once per run, and runs must not leak into each other.
- **Do not keep or change the four sequences.** They are live views of the
  controller's state.

`tests/examples/test_custom_strategy.py` checks the router's choices, checks
the comparison seed by seed, runs the example as a script, and fails if it
grows past 50 lines of code.

## Your own system

A system is plugged in through its recording. Whatever writes
`events.jsonl` in the shared format is graded like the simulator, with the
same two commands:

```bash
turncoat validate my_run.jsonl
turncoat score my_run.jsonl
```

### A live testbed run

The live backend in `backends/mininet/` already records in the shared
format, with `backend: live` in the header (see its README for running it):

```bash
python -m turncoat_mininet.run --network loopback --scenario both -o live.jsonl
turncoat score live.jsonl
```

```
live.jsonl  (live backend, strategy zt_sdn, scenario both, seed 1)
...
Attackers
  srv3     blackhole  named correctly as blackhole
           detected 3.2 s after onset
           flagged for quarantine 3.2 s after onset; no traffic after that
  srv4     sybil      named correctly as sybil
           detected 3.2 s after onset
           flagged for quarantine 3.2 s after onset; no traffic after that
```

The numbers vary from run to run, because a live run has real timing, but
the commands, the fields and the scorers are the simulator's. The IoT
clients write no file of their own: each sends its outcome to the
controller, which records it as a `report`. So one run has one recording.

`backends/mininet/tests/test_live_recording.py` holds this to account on
every change: it records a loopback run, runs `turncoat validate` and
`turncoat score` on it, and checks that its events carry every field a
simulated run's do.

### A recording from the final-year controller

The final-year project's controller wrote `data/events.jsonl` on every live
run, but in an older shape: no header, wall-clock `ts`, lines slightly out of
order, and a `seq` counter. Convert it first:

```bash
turncoat convert data/events.jsonl -o fyp_live.jsonl --strategy zt_sdn
turncoat score fyp_live.jsonl
```

`convert` reports every change it makes, validates the result, and refuses a
file it cannot convert safely. The rules are in
[event-format.md](event-format.md#live-runs).

### A recording from an outside system

Your system does not need turncoat-sdn to record. It needs to write the
lines in [event-format.md](event-format.md) to a file, in any language.
[`examples/score_outside_recording.py`](../examples/score_outside_recording.py)
shows it end to end. A toy controller, standing in for yours, imports
nothing from this package and writes plain JSON with the standard library:
three servers, round-robin routing, and a check that quarantines a server
once all of its last five tasks have timed out. Its `srv3` turns into a
blackhole 20 seconds in. Its file starts like this:

```
{"type": "header", "schema_version": "1.0", "backend": "live", "strategy": "toy_rr"}
{"type": "topology", "ts": 0.0, "graph": {"nodes": [{"id": "srv1", "kind": "server", "attack": "none"}, {"id": "srv2", "kind": "server", "attack": "none"}, {"id": "srv3", "kind": "server", "attack": "blackhole", "attack_start_s": 20.0}], "links": []}}
{"type": "route", "ts": 0.1, "task": 1, "chosen": "srv1"}
{"type": "route", "ts": 0.2, "task": 2, "chosen": "srv2"}
{"type": "report", "ts": 0.28, "task": 1, "node": "srv1", "latency_ms": 180.0, "status": "success"}
```

What a recording needs, so the scorers can grade it:

| Line | Why |
|---|---|
| `header` first, with `schema_version` `"1.0"` and `backend` | So a reader knows what it is reading. Use `live` for anything that is not the simulator |
| `topology` second, with every server's `attack` and, for attackers, `attack_start_s` | The ground truth. Detection latency is measured from the onset |
| `route` and `report` for every task | Service: availability, SLO violations, latency, traffic to attackers |
| `anomaly` with `signals`, and `node_status` once per check | What the attack classifier replays to name each attacker. `packet_drop` and `latency_tell` are the signal names it knows |
| `quarantine` | When each server was cut off |

Then turncoat-sdn grades it exactly as it grades a simulated run:

```
$ python examples/score_outside_recording.py
outside.jsonl: valid, schema 1.0, 1302 lines
outside.jsonl  (live backend, strategy toy_rr)

Service
  Tasks offered              600
  Completed                  593   98.83% availability
  Failed                       7   1.17%
  SLO violations           1.17%   deadline 500 ms
  Latency, mean / p95      180.0   / 180.0 ms
  Routed to attackers      1.17%

Attackers
  srv3     blackhole  named correctly as blackhole
           detected 2.0 s after onset
           flagged for quarantine 2.0 s after onset; no traffic after that

Detection: 1 of 1 attackers named correctly, 1 flagged, 1 cut off; 0 of 2 honest subjects mislabelled, 0 flagged.
```

`turncoat validate outside.jsonl` and `turncoat score outside.jsonl` print
the same. If validation fails, the report names each line and field to fix.

The classifier judges the evidence your system recorded, not what it
concluded. With a looser rule, quarantining `srv3` as soon as more than 40%
of its last ten tasks had timed out, the toy's `packet_drop` signal stayed
near 0.5, below the classifier's blackhole bar of 0.85, and the scorer
called `srv3` "right family as grayhole": cut off in time, but on evidence
that could not tell a blackhole from a grayhole. Record the signal strengths
your detector really saw, and the score tells you whether they were enough.

`tests/examples/test_score_outside_recording.py` checks that the toy
controller imports nothing from turncoat-sdn, that its file validates and is
byte-for-byte reproducible, that `srv3` is named, and that the script and
`turncoat score` agree.

## Known limits

- A custom attack can change what a server serves and reports, or what an
  IoT client sends and claims. It cannot change the network itself: links,
  switches and the controller are the simulator's.
- `turncoat replicate` and `turncoat compare` run built-in scenarios and
  strategies only. Until an attack or strategy is in the catalogue, compare
  it over seeds in Python, as the examples do.
- A strategy is a simulator router. `turncoat_sdn.strategies.Strategy`
  (`select(servers)`) is a separate interface with no simulator adapter yet,
  so write a router factory to run a strategy in the simulator.
- The classifier only names the attack families it knows. A new family is
  scored as missed until the classifier learns a rule for it.
- A live run is scored on the same metrics as a simulated one, but its
  numbers are not paired with a simulated seed: real timing differs between
  runs, so compare live runs with live runs.
- A converted final-year recording keeps that controller's onsets as
  configured, which can make detection latency read a few seconds long (see
  [event-format.md](event-format.md#known-limits)).
