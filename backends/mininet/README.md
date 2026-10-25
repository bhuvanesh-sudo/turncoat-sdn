# Mininet backend (optional)

**Owner:** bv · **Written in:** v1.0

## What it is

The live testbed: turncoat-sdn's strategies, trust model and attacks running
over a real emulated network instead of the simulator. Every edge server is a
Mininet host running an HTTP agent that really serves tasks. Every IoT device
is a host that really sends them, across links with real delays and bandwidth
limits. A controller in the root namespace routes, polls, detects, quarantines
and records. The recording is the same `events.jsonl` the simulator writes,
with `"backend": "live"`, so `turncoat validate` and `turncoat score` grade it
unchanged.

It is the Python package `turncoat_mininet`, kept outside the core package. This
is the **only** place in the repository allowed to import Mininet, and only
`topology.build_network` and its helpers do. The core under `src/turncoat_sdn/`
never imports anything here, and a test checks that.

## Why it exists

A benchmark that only runs in a simulator invites the question of whether
its numbers survive contact with a network. The final-year project answered
that with a live os-ken controller and a Mininet topology, but its attackers,
trust updates and detection were separate copies of the logic the simulator
later used. This backend runs the core's own code on the live network:

| Decision | Live backend uses | Same code as the simulator |
|---|---|---|
| Which server gets a task | `turncoat_sdn.cli.routers.STRATEGIES` | yes |
| How an attacker serves and reports | `turncoat_sdn.attacks` (`Sybil`, `Blackhole`, `Grayhole`, `OnOff`), built by `scenario_attacks` from `SimConfig` | yes |
| Trust after each outcome | `turncoat_sdn.trust.SimTrustModel` | yes |
| Anomaly, latency tell, timeout-rate tell, exclusion | `turncoat_sdn.sim.detect_anomalies` and `is_excluded` | yes, moved out of the event loop for this |
| Recording | `turncoat_sdn.events.EventWriter` | yes |
| Attacker placement from `--scenario`, `--attack`, `--onset` | `turncoat_sdn.cli.attack_spec.place_attacks` | yes |

So a difference between a live run and a simulated one is the network, not
two implementations drifting apart.

## How to use it

Installing Mininet and running on it are in
[INSTALL.md](../../INSTALL.md#optional-the-live-mininet-testbed). In short:

```bash
# Any OS, no root: the same processes on 127.0.0.1, no emulated links
python -m turncoat_mininet.run --network loopback --scenario sybil --onset 10 --duration 30 -o loopback.jsonl

# Linux with Mininet and Open vSwitch
sudo mn -c
sudo .venv/bin/python -m turncoat_mininet.run --scenario sybil --onset 20 --duration 60 -o live.jsonl

turncoat validate live.jsonl
turncoat score live.jsonl
```

A real loopback run on Windows, from this README's first command. The run
prints its own summary, then `turncoat validate` and `turncoat score` read
the recording as they read a simulated one:

```
{
  "recording": "loopback.jsonl",
  "offered": 914,
  "completed": 906,
  "timed_out": 0,
  "failed": 0,
  "denied": 0,
  "polls": 29,
  "quarantines": 1,
  "served": {
    "srv1": 279,
    "srv2": 294,
    "srv3": 246,
    "srv4": 95
  }
}
loopback.jsonl: valid, schema 1.0, 1870 lines
loopback.jsonl  (live backend, strategy zt_sdn, scenario sybil, seed 1)

Service
  Tasks offered              914
  Completed                  906   99.12% availability
  Failed                       0   0.00%
  SLO violations          12.14%   deadline 500 ms
  Latency, mean / p95      249.6   / 675.6 ms
  Routed to attackers      1.86%

Attackers
  srv4     sybil      named correctly as sybil
           detected 2.2 s after onset
           flagged for quarantine 2.2 s after onset; no traffic after that

Detection: 1 of 1 attackers named correctly, 1 flagged, 1 cut off; 0 of 15 honest subjects mislabelled, 0 flagged.
```

The Sybil answers honestly until its onset at 10 s. From the first poll
after it (10.19 s) it claims a load of 0.1 and answers in about 175 ms
against the fleet's 2 to 16 ms. The latency tell trips on the third such poll
(12.18 s), as in the simulator, and the 8 tasks not completed were still in
flight when the run ended. `--scenario both` (a Sybil and a blackhole, 40 s)
names both, the blackhole by its timeouts 3.2 s after onset; at 4 servers it
also shows the simulator's capacity cliff, with 40% SLO violations once two
of the four are out. Use `--servers 8` for `both`.

Options (`python -m turncoat_mininet.run --help`):

| Option | Default | Meaning |
|---|---|---|
| `--network` | `mininet` | `mininet` or `loopback` |
| `--strategy` | `zt_sdn` | Any `turncoat run` strategy |
| `--scenario` | `sybil` | Any server-attack scenario; `spoof` is simulator-only for now |
| `--attack SPEC` | | Add an attacker, as for `turncoat run`, e.g. `grayhole,node=srv2,start=20` |
| `--onset` | `0` | Onset of the scenario's attackers, in seconds |
| `--seed` | `1` | Seeds routing, task demands, attacker draws and link delays |
| `--duration` | `60` | Run length, in seconds |
| `--servers`, `--clients` | `4`, `12` | Fleet size. Attackers sit at the highest server numbers, as in the simulator |
| `--load` | `0.4` | Offered load as a fraction of farm capacity, as `SimConfig.load_factor` |
| `--work` | `sleep` | How agents spend service time: `sleep`, or `burn` to hash on the CPU as the project's agent did |
| `--warmup` | `8` | Seconds every agent and client gets to start. A run that is not ready in time stops rather than record skewed clocks or missing seconds |
| `--of-controller HOST:PORT` | | Use an OpenFlow 1.3 controller on the switches instead of standalone forwarding |
| `--api-port`, `--agent-base-port` | `8081`, `18000` | Controller API port; loopback agents listen on base + N |
| `--logs`, `-o` | `logs`, `live.jsonl` | Log directory and recording |

The pieces can also be run on their own: `python -m turncoat_mininet.node_agent`
and `python -m turncoat_mininet.iot_client` each take `--help`.

### Tests

```bash
pytest backends/mininet/tests              # no Mininet, no root; the live test skips
sudo .venv/bin/python -m pytest -m live backends/mininet/tests   # on the testbed
```

| File | What it guards |
|---|---|
| `test_node_agent.py` | The agent asks its attack the simulator's two questions: honest before the onset, a Sybil's lie and slow answer after, a blackhole's and grayhole's silent drops, on-off's honest phases, seeded drops, the worker limit, and the HTTP endpoints. Ported from the project's `test_node_agent.py` |
| `test_topology.py` | The seeded plan, addresses that match the simulator's, the linear reachability sample, teardown, and the **preflight**: every launch command parses, and every attacker in the ground truth is launched attacking from the same onset. Ported from `test_live_config_preflight.py` and `test_run_demo_mininet.py` |
| `test_controller.py` | Routing, reports and trust, the latency tell and timeout-rate tell on stand-in polls, quarantine and recovery, denial when every server is out, the clock anchored on `t0`, and the HTTP API. Every recording validates and the scorer names the attacker |
| `test_run.py` | Options, attacker placement, the guard clauses, refusing to start when processes are not ready by `t0`, and a real 8-second loopback run against a blackhole whose recording validates and scores |
| `test_imports.py` | Every backend module imports without Mininet or os-ken, and the core never imports the backend |
| `test_live_mininet.py` | `live`: a 40-second Sybil run on Mininet validates and the Sybil is named. Skips itself without Linux, root, Mininet and Open vSwitch |

## How it works inside

```
            root namespace                         Mininet hosts
  +-----------------------------------+
  |  run.py                           |      srv1..srvN   node_agent  (/task, /status)
  |   LiveController                  |           |  2 ms
  |    /route  /report   (port 8081)  |      s1..sN  edge switches
  |    polls /status every poll_s     |           |  5 ms
  |    EventWriter -> live.jsonl      |      s0  core switch --- cx (10.0.99.254)
  +-----------------------------------+           |  1-10 ms, seeded
                                             iot1..iotM   iot_client
```

One task:

1. An IoT client draws its next Poisson arrival and asks the controller
   `POST /route`. The controller runs the strategy over its current view
   (trust, claimed load, poll RTT, anomaly), draws the task's service demand
   from the seeded stream the simulator uses, records `route`, and answers
   with the server's address. If the strategy refuses, it records
   `route_denied` and answers 503.
2. The client sends `POST /task` straight to that server, across the
   emulated links. The agent waits for a free worker (`concurrency`, 4) and
   asks its attack `service_time(now, demand)`. It holds the worker that
   long, or, if the answer is `None`, holds it until the client's timeout and
   closes the connection without a reply.
3. The client reports `success`, `timeout` or `failure` with the latency on
   `POST /report`. The controller records `report`, feeds the outcome to the
   trust model, and adds it to the server's timeout window.

Every `poll_s` (1 s) the controller polls every agent's `/status` at once. The
agent asks its attack `status(now, honest)` and answers with the claimed load,
after waiting out the difference between the attack's RTT and a healthy one
(a Sybil's 220 ms against 50 ms adds 170 ms on top of the real network's
round trip). The controller runs `detect_anomalies` on the claimed loads and
measured RTTs, records `anomaly` for whatever fired, `quarantine` and
`recovered` on every change of exclusion, and closes the cycle with
`node_status`.

All of a run's processes share one start time `t0`, passed to each on its
command line `--warmup` seconds in the future, so every agent's onset and
the controller's timestamps are on one clock. The agents start first and must
answer `/status`; then the controller's API opens, and each client says
`POST /hello` before it waits for `t0`. If an agent or client is not ready by
`t0`, the run stops instead of starting. A late start would put the agents'
onsets and the recording's timestamps on different clocks and drop the first
seconds of load, which is exactly what an early version did on Windows,
where each agent took 3.6 s to import SciPy through `turncoat_sdn.cli`. The
agent no longer imports `cli`, and a test keeps it that way.

**What changed from the final-year project:**

| Project | Here | Why |
|---|---|---|
| The agent had its own `--malicious` branches and arming timer | The agent holds a core `ServerAttack` | One home for attack behaviour; the simulator and the testbed cannot drift |
| An os-ken app steered traffic with OpenFlow rewrites on a virtual IP | The controller answers `/route` and the client goes to the server directly; switches run OVS `standalone` | The benchmark measures routing and detection decisions, which need no OpenFlow. The project's VIP rewrite stays in the project |
| Per-IoT link delay from an unseeded `random.randint(1, 10)` | Drawn from the run's seed, and listed in the recording's `links` | Two runs with one seed get one network |
| Event timestamps were wall-clock | Seconds since `t0` | Schema 1.0 |
| `pingAll`, O(hosts²) | One ping per host, O(hosts) | 2,352 pings at 8 servers and 40 devices took 163 s in the project |
| The agent reported `busy_seconds` for the controller's honesty check | Not ported | Nothing in the core reads it; the latency tell and timeout-rate tell are the core's detectors |

## Known limits

- **Not yet run on Mininet from this repository.** The live code paths are
  exercised on loopback, by the tests and by the run quoted above, and the
  Mininet build follows the project's working topology. The first Mininet
  run, and checking its recording, is the v1.0 live-recording task.
- **Server attacks only.** The identity spoof (`--scenario spoof`) and the
  project's flood and wrong-key devices need the client side of the project's
  `iot_client.py` and its authentication handshake, which are not ported.
- **No OpenFlow steering.** Quarantine stops new routes to a server; it does
  not install drop rules, so a client that ignored `/route` could still reach
  it. `--of-controller` attaches an external controller, but nothing here
  programs it.
- **One machine's clock.** `t0` assumes every process shares the host's
  wall clock, which holds for Mininet and loopback, not across machines.
- **Live runs do not reproduce exactly.** The seed fixes the workload's
  draws, but thread scheduling and the network decide the order in which
  they are used. Compare live runs with paired statistics over several
  seeds, as for simulated ones.
- **Loopback is not a network.** Every agent answers polls in well under a
  millisecond, so on loopback the latency tell's baseline is near zero and
  only the Sybil's added delay stands out. Treat loopback numbers as a smoke
  test.
