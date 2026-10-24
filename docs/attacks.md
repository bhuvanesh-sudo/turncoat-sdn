# Attacks

**Owner:** ash · **Written in:** v0.3 · **Entries by:** each attack's author

## What it is

`turncoat_sdn.attacks` holds the turncoats: servers and IoT devices that
behave honestly, earn trust, and then turn hostile at their onset, `start_s`.
Each attack is a small class on one of two interfaces, `ServerAttack` for a
server and `ClientAttack` for an IoT device, and the simulator runs whatever
attacks it is given.

| Attack | After its onset, the server... | What makes it hard to catch | Label | Module | Status |
|---|---|---|---|---|---|
| [Sybil](#sybil) | claims to be idle, serves slowly, answers polls slowly | It never fails a task, so its trust stays high | `sybil` | `attacks/sybil.py` | v0.3 (ash) |
| [Blackhole](#blackhole) | accepts every task and drops it | Easy once it starts; the test is how fast | `drop` | `attacks/blackhole.py` | v0.3 (ash) |
| [Grayhole](#grayhole) | accepts every task and drops a fraction of them | Its losses blend into normal failures | `grayhole` | `attacks/grayhole.py` | v0.3 (bv) |
| [On-off](#on-off) | alternates Sybil phases with honest ones | Recovers its score in the honest phases | `onoff` | `attacks/on_off.py` | v0.3 (arj; written by bv) |
| Flood | an IoT client sends far above its normal rate | Must be told apart from a busy client | `flood` | | v0.3 (arv) |
| [Identity spoof](#identity-spoof) | an IoT client claims another device's identity | It holds the fleet key, so its cryptography is always correct | `spoof` | `attacks/spoof.py` | v0.3 (jv) |

The label is the ground truth written into the recording, and the name the
attack scorer checks its verdict against.

## Why it exists

An attacker that is hostile from second zero is easy to catch: it has no trust
to spend and no honest history to hide behind. A real turncoat earns a high
score first. The benchmark needs both behaviours, and it needs to know exactly
when the switch happened, so detection latency means "time since it turned",
not "time since the run began".

Delayed onset is not a formality. It changes results. Run `zt_sdn` against a
blackhole that turns at 30 s instead of at 0 s:

| Onset | Isolated | Scorer's label | Why |
|---|---|---|---|
| 0 s | 3 s after onset | `blackhole` | Every outcome in its recent window is a timeout: rate 1.0 |
| 30 s | 5 s after onset | `grayhole` on 4 of 5 seeds | The window still holds honest successes when the tell fires (rate 0.8, under the 0.85 bar), and quarantine stops new outcomes arriving |

The defence works both times. Only with an onset does the benchmark show that
`zt_sdn` contains a late blackhole faster than it can tell what it is.
`tests/attacks/test_onset.py` pins this.

## How to use it

Delay a scenario's built-in attackers with `SimConfig(attack_start_s=...)`.
The onset goes into the recording, and the scorer measures detection from it:

```python
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import SimConfig, simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

hooks = {"trust": SimTrustModel, "latency_tell": latency_tell}
config = SimConfig(attack_start_s=30.0)  # both attackers turn at 30 s
zt_sdn = STRATEGIES["zt_sdn"]

with EventWriter("both.jsonl", backend="sim", seed=1000, scenario="both") as rec:
    run = simulate(zt_sdn, "both", 1000, config=config, recorder=rec, **hooks)
print(run.time_to_isolate_s)

for r in score_run(read_events("both.jsonl")):
    if r.truth != "none":
        print(r.subject, r.predicted, r.onset_s, r.detection_latency_s)
# 33.0
# srv7 grayhole 30.0 None
# srv8 sybil 30.0 2.0
```

The Sybil is named 2 s after it turns. The blackhole is isolated but labelled
a grayhole, as above, so it has no exact-label latency; the attack report
marks it `FAMILY`.

To choose the attackers yourself, pass `attacks`, a mapping from node index
to attack. It replaces the scenario's attackers, and each attack carries its
own onset:

```python
from turncoat_sdn.attacks import Blackhole, Sybil

attacks = {7: Sybil(start_s=20.0), 2: Blackhole(start_s=45.0)}
run = simulate(zt_sdn, "both", 1000, attacks=attacks, **hooks)
```

The scenario name is still the run's label. `attacks={}` runs with no server
attacker.

Client attackers go in `client_attacks`, keyed by client index: client 0 is
`iot1`, client 37 is `iot38`. Any client attacker turns on the IoT devices
and the controller's admission check for that run:

```python
from turncoat_sdn.attacks import IdentitySpoof

spoof = {37: IdentitySpoof(start_s=15.0, target=0)}  # iot38 claims to be iot1
run = simulate(zt_sdn, "clean", 1000, client_attacks=spoof, **hooks)
print(run.client_attack_requests, run.client_attack_refused, run.honest_refused)
# 53 53 0
```

`client_attacks={}` runs with no client attacker. From the command line,
`turncoat run --attack` adds either kind (see [cli.md](cli.md)).

## How to write an attack

An attack is a subclass of `ServerAttack` with a `name` and one or two
methods. The base class keeps the server honest until `start_s`, so you only
describe what happens after it turns.

| Method | The simulator asks | Return | Default |
|---|---|---|---|
| `serve(now, demand_s, rng)` | How long does this task hold a worker? | Seconds, or `None` to accept it and never answer (the client times out) | `demand_s`: serve honestly |
| `report(now, honest, jitter_ms, rng)` | What does the server report at this poll? | A `Status(claimed_cpu, rtt_ms)` | `honest`: report the truth |

`honest` is what an honest server in this one's place would report: its true
load and the healthy round-trip plus this poll's jitter. `jitter_ms` is passed
separately for an attack that sets its own round-trip.

Here is a complete attack. The *fast liar* claims to be idle but, unlike the
Sybil, burns nothing visible: it serves and answers at full speed.

```python
from turncoat_sdn.attacks import ServerAttack, Status


class FastLiar(ServerAttack):
    """Claims to be idle, but serves and answers at full speed."""

    name = "fast_liar"

    def report(self, now, honest, jitter_ms, rng):
        return Status(claimed_cpu=0.05, rtt_ms=honest.rtt_ms)


run = simulate(zt_sdn, "clean", 1000, attacks={7: FastLiar(start_s=30.0)}, **hooks)
print(run.time_to_isolate_s, round(run.malicious_share, 3))
# None 0.137
```

`zt_sdn` never isolates it, and while it is hostile it draws 0.137 of all
tasks, more than an eighth share of the 90 s it is lying for (about 0.094).
Its lie works and nothing catches it: the latency tell needs a slow answer,
and the trust score floors well above 0.3 (see
[The trust model](trust-model.md)). It does little damage only because it
serves honestly. That is the kind of result an attack exists to surface.

### A client attack

An attack by an IoT device subclasses `ClientAttack`. The device's ordinary
traffic, sent as itself, comes from the simulator's shared arrival stream all
run, whatever the attack does. From its onset the attack also sends requests
of its own, always from the device's own address, and decides two things
about them:

| Method | The simulator asks | Return | Default |
|---|---|---|---|
| `interval(now, rng)` | How long until your next request? | Seconds, or `None` to stop | `None`: one request at the onset |
| `claim(own, now)` | Which device does this request claim to be? | A client index | `own`: its own identity |

The controller's admission check then admits the request into routing, or
refuses it and records an `auth_denied`. That decision is the simulator's,
never the attack's. The identity spoof below claims another device on a fixed
beat. A flood would claim its own identity and return short intervals drawn
from `rng`.


- **Draw randomness only from `rng`.** Each attacker gets its own stream,
  seeded from the run's seed and its node index. A random attack stays
  reproducible, and its draws never shift the workload the strategies are
  paired on. Never use the global `random` module.
- **Keep no per-run state on the instance.** One instance may serve many runs.
  Work out anything time-dependent, such as an on-off phase, from `now`.
- **Use a label the classifier knows.** Use `grayhole`, `onoff`, `flood` or
  `spoof` as in the table above; the attack classifier's
  `GROUND_TRUTH_ALIASES` lists every accepted name. An unknown label still
  records and validates, but every verdict on it scores as a miss.
- **Don't override `service_time` or `status`** (or, for a client attack,
  `first_request_s`, `next_request_s` and `identity`). They apply the onset,
  then call your methods.

### Adding one to the catalogue

1. Put the class in `src/turncoat_sdn/attacks/<attack>.py` and export it from
   `attacks/__init__.py`.
2. If it should be a built-in scenario, add a branch to `scenario_attacks` (a
   server attack) or `scenario_client_attacks` (a client attack) in
   `sim/config.py` and its name to `SCENARIOS`. Take its settings from
   `SimConfig` and its onset from `cfg.attack_start_s`, as the Sybil does. To
   make it a `turncoat run --attack` choice too, add it to
   `cli/attack_spec.py`.
3. Test it in `tests/attacks/`. Test the profile on its own (honest before
   `start_s`, hostile after), then in the simulator, then that the attack
   scorer names it. If the classifier cannot name it, record that honestly as
   a known limit; it is a finding, not a failure.
4. Add its entry to [The attacks](#the-attacks) below, in the same pull
   request.

## How it works inside

**The interface.** `ServerAttack` (in `attacks/base.py`) has two methods the
simulator calls, `service_time` and `status`. Each checks
`active(now) = now >= start_s`: before the onset it returns the honest answer
unchanged, after it calls the attack's `serve` or `report`.

**Where the simulator calls it.** The simulator calls `service_time` when a
task starts to occupy a worker, which is either on arrival or when it leaves
the backlog. A `None` result schedules a timeout `task_timeout_s` later in
place of a completion. It calls `status` at every poll, after drawing that
node's jitter, so jitter draws are the same with or without attackers.

**Ground truth.** The `topology` event writes each attacker's
`ground_truth()`: its `attack` label and `attack_start_s`. Honest servers are
written with `attack: "none"` and no onset.

**What counts after the onset.** `malicious_tasks` (and `malicious_share`)
count only tasks routed to an attacker after it turned, since traffic to an
honest server is not a cost. `time_to_isolate_s` is the first poll at which
every attacker has turned *and* is excluded. With an onset of 0 both are
exactly what they were before v0.3.

**Client attacks and admission.** A run with a client attacker models
`n_clients` IoT devices (40, `iot1` to `iot40` at `10.0.0.1` to
`10.0.0.40`, as in the final-year project). Each arrival is attributed to a
device by a draw from a stream of its own, so the workload does not move.
Every request, ordinary or the attacker's, passes the admission check in
`sim/admission.py` before routing. A refused one is never offered to the
router: it counts in `RunResult.client_attack_refused` or
`honest_refused`, not in `offered`. An admitted attacker request takes its
service time from the attacker's own stream and is routed like any task.
`topology` lists every device with its address and ground truth, and every
`route` carries the sender's `client_ip`. A run with no client attacker
models no devices and records exactly what it did before v0.3.

**Moving the built-in attacks changed nothing.** The Sybil and the blackhole
were branches in the simulator's event loop until v0.3. They now run through
the interface with the same arithmetic, and the golden-file tests from the
final-year project and the CLI's fixed-seed scores all pass unchanged.

## The attacks

Each entry is written by the attack's author.

### Sybil

**Module:** `attacks/sybil.py` · **Label:** `sybil` · **Author:** ash

Once it turns, it reports a load of 0.1 whatever the truth, serves every
task at half speed (`slowdown=2.0`) because it burns CPU, and answers polls at
220 ms against a healthy 50 ms. Its claim of being idle attracts traffic from
load-aware strategies.

It never fails a task, so its trust stays high and the trust formula alone
cannot isolate it. The latency tell catches it: it claims to be idle but
answers about four times slower than the fleet. Keep `slowdown` under 2.5.
Past that it cannot keep up with its share, times tasks out, and becomes a
failing node that trust isolates on its own, which is a much easier attack.

Settings: `claimed_cpu`, `slowdown`, `rtt_ms`, taken in scenarios from
`SimConfig.sybil_*`.

### Blackhole

**Module:** `attacks/blackhole.py` · **Label:** `drop` · **Author:** ash

Once it turns, it accepts every task, holds the worker and never answers,
so every client times out after 2 s. It still answers polls promptly and
reports its load honestly.

Trust alone settles at about 0.36 for it, above the line, so the timeout-rate
tell is what isolates it. Its label stays `drop`, the name every earlier
recording used; the attack scorer reports it as `blackhole`.

### Grayhole

**Module:** `attacks/grayhole.py` · **Label:** `grayhole` · **Author:** bv

Once it turns, it drops each task it accepts with probability
`drop_fraction` (default 0.5). A dropped task holds its worker and never
answers, so the client times out after 2 s, as with the blackhole. It serves
every other task honestly, answers polls promptly and reports its load
honestly. Whether a task is dropped is one draw per task from the attacker's
own seeded stream, so a seed drops the same tasks every time and the paired
workload never moves.

The observed timeout rate runs above the fraction, about 0.6 at the default.
Each dropped task holds a worker for the full timeout, so tasks queued behind
it give up too. That rate sits between an honest node's and a blackhole's,
which is what the classifier splits on: the timeout-rate tell fires above
0.40, and a median rate under 0.85 is named `grayhole`, not `blackhole`.

```bash
turncoat run --strategy zt_sdn --scenario grayhole --seed 1 -o grayhole.jsonl
turncoat score grayhole.jsonl
```

`zt_sdn` isolates it 3 s after onset on seed 1 and names it exactly. Over
seeds 1 to 10 and 1000 to 1004 it isolates the grayhole on every seed. The
scorer names it `grayhole` on 14 of 15 seeds when it is hostile from the start,
and on 13 of 15 when it turns at 30 s; the misses are one `blackhole` and the
abstentions under [Known limits](#known-limits). `round_robin` on seed 1 keeps
sending it an eighth of all traffic, and 9.4% of all tasks fail against
`zt_sdn`'s 0.07%.

Settings: `drop_fraction`, taken in the `grayhole` scenario from
`SimConfig.grayhole_drop_fraction`. Keep it between about 0.45 and 0.7 for
the scorer to name it. Below that the tell fires only intermittently or not at
all, and above it the median rate starts to reach the blackhole bar.

### On-off

**Module:** `attacks/on_off.py` · **Label:** `onoff` · **Author:** bv, for arj's
v0.3 task

Once it turns, it lies like the Sybil for `on_s` seconds (claims a load of
0.1, serves at half speed, answers polls at 220 ms), then behaves honestly for
`off_s` seconds, and repeats. The defaults are 10 s each, a 20 s period. The
phase is worked out from `now`, so it draws no random numbers and keeps no
per-run state.

Its hostile phase lies rather than drops on purpose. The classifier tells
on-off from its sibling by intermittency inside the load-dishonesty family:
a liar that goes measurably honest between phases is `onoff`, a steady one is
`sybil`. An attacker that dropped tasks in its hostile phases would be scored
as a grayhole or blackhole.

```bash
turncoat run --strategy zt_sdn --scenario onoff --seed 1 -o onoff.jsonl
turncoat score onoff.jsonl
```

`zt_sdn` flags it 3 s after onset, but cannot keep it out. Each honest phase
drains its anomaly level and lifts its quarantine, so on seed 1, 473 tasks
still reach it after it was first flagged and it draws 6.5% of all traffic,
against `round_robin`'s eighth (12.5%). It never fails a task, so the cost is
latency, not availability. That recovery is the attack.

It can only be named once it has gone quiet and come back, so detection
latency is about one period plus the tell's 2 s reaction: 22 s at the
defaults. The scorer names it `onoff` on all 15 seeds tried (1 to 10, 1000 to
1004), both hostile from the start and turning at 30 s, and for every phase
pair from 3 s/3 s to 20 s/10 s. Where it stops is under
[Known limits](#known-limits).

Settings: `on_s`, `off_s`, and the Sybil's `claimed_cpu`, `slowdown` and
`rtt_ms`. The `onoff` scenario takes them from `SimConfig.onoff_on_s`,
`SimConfig.onoff_off_s` and `SimConfig.sybil_*`.

### Identity spoof

**Module:** `attacks/spoof.py` · **Label:** `spoof` · **Author:** jv

Once it turns, the device sends a request claiming another device's identity
every `interval_s` seconds (default 2 s, the project's reporting period),
from its own address. Its ordinary traffic as itself carries on throughout.
The scenario's spoofer is `iot38` impersonating `iot1`, as in the final-year
project's live configuration.

It holds the fleet key. The project's PRESENT-80 key was shared by every
device, so the spoofer's challenge response is always correct: the key proves
membership of the fleet, not ownership of an identity. The simulator does not
model the cipher for that reason. What stops the spoofer is the controller
binding each device id to a source address, ported from the project's
`IdentityBinding`, under one of two rules set by
`SimConfig.identity_binding`:

- **`roster`** (the default): each device id is provisioned to its own
  address before the run. A claim from any other address is refused, whether
  or not the real device has spoken yet. This is the project's fix after
  live run 9.
- **`tofu`**, trust on first use: the first address to claim an id is pinned
  to it. A spoofer that claims an identity before its owner does gets it.

```bash
turncoat run --strategy zt_sdn --scenario spoof --seed 1 -o spoof.jsonl
turncoat score spoof.jsonl
```

Under `roster`, every request it sends as `iot1` is refused at admission
(61 of 61 on seed 1) and recorded as an `auth_denied` with kind `ip_pin`.
The scorer names `iot38` `spoof` at its first attempt, 0 s after onset, on
all 15 seeds tried (1 to 10, 1000 to 1004), hostile from the start and
turning at 30 s, and mislabels no honest device. A refused spoof costs the
fleet nothing: offered tasks, latencies and per-server load are identical to
the `clean` run of the same seed for all five strategies. No server is ever
quarantined, because none attacked; the spoofer is stopped before routing.

Under `tofu` it depends on who speaks first. `iot1`'s first request falls
0.05 to 1.88 s into the run across those seeds. Turning at 30 s, the spoofer
is refused exactly as under `roster`. Hostile from the start, it claims
`iot1` before `iot1` does on every seed: all its requests are admitted and
routed as `iot1`'s, and the real `iot1` is locked out, 168 to 225 of its
requests refused per run. This is live run 9, where `iot1`'s first handshake
failed and `iot38` took the identity. Turning at 1 s, it still wins on 4 of
the 15 seeds; at 2 s, on none.

```bash
turncoat run --scenario spoof --identity-binding tofu -o tofu.jsonl
```

Settings: `target`, `interval_s`, and `start_s`. The `spoof` scenario takes
them from `SimConfig.spoof_attacker`, `spoof_target`, `spoof_interval_s` and
`attack_start_s`. `--attack spoof,client=iotN,target=iotM,start=S` places one
from the command line.

## Known limits

- **Flood has its interface but not its attack yet.** `ClientAttack` is the
  client-side counterpart to `ServerAttack` that flood needs: a flood claims
  its own identity and sends at a short, random interval. The simulator still
  has no per-client rate tell to flag it; that arrives with the flood attack.
- **A spoof that wins under `tofu` is blamed on its victim.** The refusals
  come from the real `iot1`'s own address, so the scorer names `iot1`
  `spoof` and misses `iot38`, which is never refused. The scorer keys on the
  address that sent a refused request, which is right whenever the binding
  holds. Pinned in `tests/attacks/test_spoof.py`.
- **The cipher is not modelled.** Every enrolled device passes the
  cryptographic check, because the project's key was fleet-wide. A device
  without the key (`bad_credentials`, refused with kind `bad_response`) and
  per-device keys, which would stop the spoof without any binding, are not
  in the simulator.
- **Arrivals are spread evenly over devices.** Each arrival comes from a
  device chosen uniformly at random, so every device sends about 1.6 tasks a
  second. The live devices reported on a fixed 2 s beat.
- **No CPU-honesty check in the simulator.** The live controller compared a
  server's claimed load with its observed load. The simulator does not model
  that check, so a liar that stays fast, like the `FastLiar` above, is never
  flagged.
- **On-off needs phases of the right length.** Measured against `zt_sdn`
  in a 120 s run, pinned in `tests/attacks/test_on_off.py`:
  - An honest phase of 2 s or less is too short to show three clean polls,
    so the attacker is labelled `sybil`. The family is right. The
    classifier's own estimate of the floor, `ONOFF_MIN_GOOD_PHASE_S`, is 4 s;
    3 s still works in the simulator.
  - Toggling every 2 s or faster, both phases too short, it is never flagged
    at all: the latency tell never collects consecutive strikes.
  - Long phases need a long run. The verdict is the modal label, and every
    poll before the first resumption reads as a Sybil, so a 30 s/30 s
    attacker in a 120 s run is named `onoff` at 62 s but outvoted by `sybil`.
    Keep the run to about four periods or more, and the replay window to two.
- **A grayhole contained by trust alone goes unnamed.** On some seeds
  `zt_sdn`'s trust score falls below 0.3 before the timeout-rate tell has its
  four outcomes. Quarantine then stops new outcomes, so no `anomaly` event is
  ever recorded and the scorer abstains (`none`). It is contained, but
  unlabelled: seed 3 turning at 30 s, pinned in `tests/attacks/test_grayhole.py`.
  The simulator records no trust-collapse signal the classifier could use.
- **A late blackhole is often labelled a grayhole.** See
  [Why it exists](#why-it-exists): `zt_sdn` contains it before its timeout
  rate reaches the blackhole bar. The family is right; the exact label is not.
