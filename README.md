# turncoat-sdn

**A reproducible benchmark for trust-aware SDN load balancers under delayed-onset ("turncoat") attacks.**

[![CI](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Status: v0.2 in progress](https://img.shields.io/badge/status-v0.2%20in%20progress-orange.svg)](CHANGELOG.md)

> **Status: v0.2 in progress.** v0.1 is merged: the simulator, the five
> strategies and the trust model run on a plain laptop. v0.2 adds the shared
> `events.jsonl` format with a validator, the scorers that read it, and the
> `turncoat run`, `validate` and `score` commands. See the
> [release plan](#release-plan).

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
| **Simulator** | Seeded discrete-event model of edge servers, IoT clients and a load-balancing strategy. Needs no switch, root access or Mininet. | v0.1; records runs to `events.jsonl` from v0.2 |
| **Strategies and trust model** | `random`, `round_robin`, `least_conn`, `no_trust` and `zt_sdn`, plus the trust calculator, EdgeScore selector, isolation threshold and anomaly gate. | v0.1 |
| **Event format** | One JSON object per line, covering every routing decision, outcome, classification and quarantine, plus the ground truth. Versioned, with a validator. | v0.2 |
| **Scorers** | Detection accuracy and latency with a confusion matrix, availability, NFR and interval metrics. | v0.2 |
| **Attack library** | Six hostile behaviours: sybil, blackhole, grayhole, on-off, flood and identity spoof. Each has a configurable onset `start_s`. | v0.3; the simulator has sybil and drop built in |
| **Statistics** | Paired Wilcoxon tests with Holm correction and bootstrap CIs. | v0.4 |

## Quick start (v0.2)

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

Then record one simulated run, check the file, and score it:

```bash
turncoat run --strategy zt_sdn --scenario both --seed 1 -o run.jsonl
turncoat validate run.jsonl
turncoat score run.jsonl
```

```
run.jsonl  (sim backend, strategy zt_sdn, scenario both, seed 1)

Service
  Tasks offered            7,624
  Completed                7,609   99.80% availability
  Failed                       5   0.07%
  SLO violations          11.63%   deadline 500 ms
  Latency, mean / p95      240.0   / 684.9 ms
  Routed to attackers      0.46%

Attackers
  srv7     blackhole  named correctly as blackhole
           detected 3.0 s after onset
           flagged for quarantine 3.0 s after onset; no traffic after that
  srv8     sybil      named correctly as sybil
           detected 3.0 s after onset
           flagged for quarantine 3.0 s after onset; no traffic after that

Detection: 2 of 2 attackers named correctly, 2 flagged, 2 cut off; 0 of 6 honest subjects mislabelled, 0 flagged.
```

Both attackers are named and cut off three seconds after they start. Run the
same seed with `--strategy round_robin` and the controller still flags them,
but nothing acts on it: a quarter of all traffic keeps landing on attackers.
Every command and option is in [docs/cli.md](docs/cli.md).

### Where this is going

More attacks arrive in v0.3 (`--scenario on-off` among them), and
comparisons over many seeds in v0.4:

```bash
turncoat run --scenario on-off --strategy zt_sdn --seed 1 -o run.jsonl
turncoat compare --strategies zt_sdn,least_conn --seeds 30
```

## Release plan

| Release | Goal | Demo at the end |
|---|---|---|
| v0.1 | The simulator runs on its own | `pytest` passes on a clean machine with no os-ken; one simulated run completes |
| **v0.2** | One event format, scorers read it | `turncoat run` then `turncoat score` prints detection results |
| v0.3 | The full attack catalogue | All six attacks run and are scored, each with its onset visible |
| v0.4 | Statistics people can trust | `turncoat compare` prints p-values and CIs over 30 seeds |
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
|   |-- scoring/      # attack, nfr, interval, availability
|   |-- stats/        # Wilcoxon + Holm, bootstrap CIs, aggregator
|   `-- cli/          # turncoat run / validate / score (compare in v0.4)
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
- [docs/cli.md](docs/cli.md): every `turncoat` command and option
- [docs/scoring.md](docs/scoring.md): what each score means
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
