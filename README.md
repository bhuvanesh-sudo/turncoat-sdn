# turncoat-sdn

**A reproducible benchmark for trust-aware SDN load balancers under delayed-onset ("turncoat") attacks.**

This repository is part of the following parent project:

- **Parent Repository:** [Zero-Trust-Enabled-SDN-Architecture](https://github.com/a5hx/Zero-Trust-Enabled-SDN-Architecture)

[![CI](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Status: v0.4 in progress](https://img.shields.io/badge/status-v0.4%20in%20progress-orange.svg)](CHANGELOG.md)

> **Status: v0.4 in progress.** v0.1 to v0.3 are merged: the simulator, the
> five strategies and the trust model run on a plain laptop, every run records
> to the shared `events.jsonl` format, `turncoat run`, `validate` and `score`
> grade it, and the attack catalogue gives every attack its own onset
> `start_s`. v0.4 adds statistics: `turncoat replicate` runs many paired seeds
> into one results CSV and prints every metric with a 95% bootstrap confidence
> interval. See the [release plan](#release-plan).

---

## The turncoat problem

Picture an edge network where eight servers share the work of forty IoT
devices. A Zero Trust controller gives every server a trust score and sends
new work to the servers it trusts most. Now one of those servers is a
**turncoat**. For the first two minutes it behaves perfectly and earns a high
score. Then it turns: it lies about how busy it is, quietly drops one task in
five, or flips between honest and malicious to keep its score just above the
line.

Our final-year project built that world, and found a blind spot the published
design did not expect:

> The trust formula `T = 0.35·R + 0.25·B + 0.25·H − 0.15·A` **cannot isolate a
> competent liar.** A node that lies about its load but still completes tasks
> keeps R ≈ 1.0 and B ≈ 0.96, so its trust never falls below **0.44**, well
> above the 0.3 isolation threshold. Only an independent anomaly gate catches it.

How would anyone else know whether *their* trust model has the same blind
spot? Most trust-aware systems are evaluated on private testbeds, with
home-made attackers and home-made metrics, so the results can't be compared
with each other. **turncoat-sdn** turns our delayed-onset attackers, event
recordings, ground-truth scorers and paired statistics into a benchmark anyone
can run on a laptop.

## What it is made of

```
attacks (who turns, how, and when)
        |
        v
simulator  or  live Mininet testbed
        |
        v
events.jsonl   <- one shared recording format
        |
        v
scorers --> statistics --> report
        (who was caught, how fast, at what cost)
```

| Part | What it does | Status |
|---|---|---|
| **Simulator** | Seeded discrete-event model of edge servers, IoT clients and a load-balancing strategy. Needs no switch, root access or Mininet. | v0.1; records runs to `events.jsonl` from v0.2; runs attack profiles with an onset from v0.3 |
| **Strategies and trust model** | `random`, `round_robin`, `least_conn`, `no_trust` and `zt_sdn`, plus the trust calculator, EdgeScore selector, isolation threshold and anomaly gate. | v0.1 |
| **Event format** | One JSON object per line, covering every routing decision, outcome, classification and quarantine, plus the ground truth. Versioned, with a validator. | v0.2 |
| **Scorers** | Detection accuracy and latency with a confusion matrix, availability, NFR and interval metrics. | v0.2 |
| **Attack library** | Six hostile behaviours: sybil, blackhole, grayhole, on-off, flood and identity spoof. Each has a configurable onset `start_s`. | v0.3; sybil, blackhole, grayhole, on-off and identity spoof are in |
| **Statistics** | A results CSV over many paired seeds, bootstrap CIs on every metric, paired Wilcoxon tests with Holm correction. | v0.4; results file and bootstrap CIs are in; descriptive summaries and a strategy benchmark runner from v0.3 |

## The attack catalogue

Every attack is a turncoat: honest until its onset `start_s`, hostile after.
Each is a small class on one of two interfaces, `ServerAttack` for a server
and `ClientAttack` for an IoT device, and the label is the ground truth the
scorer checks its verdict against.

| Attack | After its onset, the attacker... | Label | Scenario | Status |
|---|---|---|---|---|
| Sybil | claims to be idle, serves slowly, answers polls slowly | `sybil` | `sybil`, `both` | in (ash) |
| Blackhole | accepts every task and drops it | `drop` | `drop`, `both` | in (ash) |
| Grayhole | accepts every task and drops a fraction of them | `grayhole` | `grayhole` | in (bv) |
| On-off | alternates Sybil phases with honest ones | `onoff` | `onoff` | in (arj) |
| Flood | an IoT client sends far above its normal rate | `flood` | | v0.3 (arv) |
| Identity spoof | an IoT client claims another device's identity | `spoof` | `spoof` | in (jv) |

How each one behaves, what catches it, and how to write your own are in
[docs/attacks.md](docs/attacks.md).

## Quick start (v0.4)

Install from source and run the test suite (full details in
[INSTALL.md](INSTALL.md)):

```bash
git clone https://github.com/bhuvanesh-sudo/turncoat-sdn.git
cd turncoat-sdn
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
turncoat --version
```

The core needs only NumPy and SciPy. It never imports os-ken, Ryu or Mininet,
and a test enforces that.

Then record one simulated run against a grayhole, a server that quietly
drops half the tasks it accepts, check the file, and score it:

```bash
turncoat run --strategy zt_sdn --scenario grayhole --seed 1 -o run.jsonl
turncoat validate run.jsonl
turncoat score run.jsonl
```

```
run.jsonl  (sim backend, strategy zt_sdn, scenario grayhole, seed 1)

Service
  Tasks offered            7,624
  Completed                7,610   99.82% availability
  Failed                       5   0.07%
  SLO violations           9.90%   deadline 500 ms
  Latency, mean / p95      220.6   / 639.0 ms
  Routed to attackers      0.09%

Attackers
  srv8     grayhole   named correctly as grayhole
           detected 3.0 s after onset
           flagged for quarantine 3.0 s after onset; no traffic after that

Detection: 1 of 1 attackers named correctly, 1 flagged, 1 cut off; 0 of 7 honest subjects mislabelled, 0 flagged.
```

The grayhole is named, not mistaken for a blackhole, and cut off three
seconds after it starts. Run the same seed with `--strategy round_robin` and
the controller still flags it, but nothing acts on it: an eighth of all
traffic keeps landing on it and 9.4% of all tasks fail. `--scenario both` runs
a Sybil and a blackhole together, `--scenario onoff` a Sybil that keeps
going honest to win back its place, and `--scenario spoof` an IoT device
claiming another's identity, refused at admission. Every command and option
is in [docs/cli.md](docs/cli.md).

To make an attacker turn later, give it an onset: `--onset 30` delays the
scenario's attackers, and `--attack sybil,node=srv3,start=30` adds one of
your own beside them. From Python,
`SimConfig(attack_start_s=30.0)` delays a scenario's attackers and
`simulate(..., attacks={7: Grayhole(start_s=30.0)})` places your own; the
onset is written into the recording and detection is measured from it (see
[docs/attacks.md](docs/attacks.md#how-to-use-it)).

### Many seeds, with confidence intervals

One run is one seed. To compare strategies, run them all on the same 30
seeds and put an interval on every mean:

```bash
turncoat replicate --scenarios both --seeds 30 -o results.csv
```

```
Ran 150 runs (5 strategies x 1 scenario x 30 seeds, 1 to 30) in 31 s
Wrote results.csv (150 rows, results format 1.0)

Mean over seeds, with 95% bootstrap confidence interval [low, high] (10,000 resamples)

both  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          25.10 [24.79, 25.40]     23.36 [23.16, 23.57]     38.19 [37.24, 39.19]     17.05 [16.75, 17.37]     12.09 [11.85, 12.34]
  Failed (%)                  12.16 [12.04, 12.27]     12.09 [12.08, 12.10]     12.48 [11.91, 13.05]        3.98 [3.90, 4.06]        0.10 [0.09, 0.12]
  Routed to attackers (%)     25.02 [24.85, 25.17]     24.99 [24.99, 24.99]     15.34 [14.32, 16.34]     14.35 [14.19, 14.53]        0.36 [0.33, 0.39]
  ...
```

`results.csv` has one row per run with every metric as a column, ready for
a spreadsheet or for `turncoat compare`. The full seven-scenario comparison,
and how to read it, is in [docs/results.md](docs/results.md).

### Where this is going

Paired tests arrive later in v0.4:

```bash
turncoat compare --strategies zt_sdn,least_conn --seeds 30
```

## Release plan

| Release | Goal | Demo at the end |
|---|---|---|
| v0.1 | The simulator runs on its own | `pytest` passes on a clean machine with no os-ken; one simulated run completes |
| v0.2 | One event format, scorers read it | `turncoat run` then `turncoat score` prints detection results |
| v0.3 | The full attack catalogue | All six attacks run and are scored, each with its onset visible |
| **v0.4** | Statistics people can trust | `turncoat compare` prints p-values and CIs over 30 seeds |
| v1.0 | Ready for others | A stranger follows this README from zero to a comparison table |

## Project layout

```
turncoat-sdn/
|-- src/turncoat_sdn/
|   |-- sim/          # seeded discrete-event simulator
|   |-- attacks/      # one file per attack profile
|   |-- strategies/   # random, round_robin, least_conn, no_trust, zt_sdn
|   |-- trust/        # trust calculator, edge selector, thresholds
|   |-- events/       # schema, JSONL writer and reader, validator
|   |-- scoring/      # attack, nfr, interval, availability, benchmark
|   |-- stats/        # descriptive, bootstrap CIs, results file (Wilcoxon + Holm next)
|   `-- cli/          # turncoat run / validate / score / replicate (compare next)
|-- backends/mininet/ # optional live testbed (v1.0)
|-- examples/         # custom scenario, strategy and attack (v1.0)
|-- docs/             # documentation set
|-- tests/
`-- .github/          # CI workflow, PR and issue templates
```

## Documentation

Start with [docs/concepts.md](docs/concepts.md) for trust, EdgeScore, the gate
and ground truth. Then:

- [docs/simulator.md](docs/simulator.md): how a run works, why seeds are
  paired, and how to record a run
- [docs/event-format.md](docs/event-format.md): every line a recording can
  hold, and how to validate one
- [docs/attacks.md](docs/attacks.md): how each turncoat behaves, what catches
  it, and how to write a new one
- [docs/cli.md](docs/cli.md): every `turncoat` command and option
- [docs/scoring.md](docs/scoring.md): what each score means
- [docs/statistics.md](docs/statistics.md): confidence intervals and paired
  tests over many runs, and
  [docs/benchmark-statistics.md](docs/benchmark-statistics.md) for
  descriptive summaries
- [docs/results.md](docs/results.md): a full comparison over 30 seeds, and how
  to read it
- [docs/strategies.md](docs/strategies.md) and
  [docs/trust-model.md](docs/trust-model.md): the baselines and the trust
  formula's blind spot
- [docs/architecture.md](docs/architecture.md): how the parts fit, and what
  may import what

[docs/README.md](docs/README.md) lists every page, its owner and its release.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you push. It covers the
release-branch workflow, commit style, the review rota and the definition of
done.
Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Origin

turncoat-sdn is carved out of our final-year project, *Zero Trust–Enabled SDN
Architecture for Secure and Intelligent Load Balancing in Edge Networks*, at
the Department of Computer Science and Engineering, Amrita Vishwa Vidyapeetham,
Coimbatore, under the guidance of Dr. Radhika N.

## Team

| Handle | Name | Track |
|---|---|---|
| bv | Bhuvanesh S | Simulator and release |
| arj | Arjun Krishnakumar | Event format and live recording |
| ash | Ashwin Kumar RM | Trust model and attacks |
| arv | Aravind Kumar M | Strategies, scoring and statistics |
| jv | K R Jeevan Raj | Repo, CLI and tests |

## License

[MIT](LICENSE)
