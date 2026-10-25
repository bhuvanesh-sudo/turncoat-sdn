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
| A new way to route tasks | A strategy | *v1.0, arv* | [Your own strategy](#your-own-strategy) |
| A system of your own | An `events.jsonl` recording | *v1.0, arv and arj* | [Your own system](#your-own-system) |

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

*To be written by arv in v1.0, with `examples/` code for a custom strategy.*

## Your own system

*To be written by arv and arj in v1.0: scoring a recording from an outside
system, and the live recording check.*

## Known limits

- A custom attack can change what a server serves and reports, or what an
  IoT client sends and claims. It cannot change the network itself: links,
  switches and the controller are the simulator's.
- `turncoat replicate` and `turncoat compare` run built-in scenarios only.
  Until an attack is in the catalogue, compare it over seeds in Python, as
  the example does.
- The classifier only names the attack families it knows. A new family is
  scored as missed until the classifier learns a rule for it.
