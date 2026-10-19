# turncoat-sdn

**A reproducible benchmark for trust-aware SDN load balancers under delayed-onset ("turncoat") attacks.**

[![CI](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bhuvanesh-sudo/turncoat-sdn/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Status: v0.1 in progress](https://img.shields.io/badge/status-v0.1%20in%20progress-orange.svg)](CHANGELOG.md)

> **Status: v0.1 (scaffold).** The package layout, CI and contribution workflow
> are in place. The simulator, strategies and trust model are being ported in
> this release. The commands under "Where this is going" do not work yet. See
> the [release plan](#release-plan).

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

| Part | What it does |
|---|---|
| **Simulator** | Seeded discrete-event model of edge servers, IoT clients and a load-balancing strategy. Needs no switch, root access or Mininet. |
| **Attack library** | Six hostile behaviours: sybil, blackhole, grayhole, on-off, flood and identity spoof. Each has a configurable onset `start_s`. |
| **Event format** | One JSON object per line, covering every routing decision, outcome, classification and quarantine, plus the ground truth. |
| **Scorers and statistics** | Detection accuracy and latency, availability, throughput and latency over time, plus paired Wilcoxon tests with Holm correction and bootstrap CIs. |

## Quick start (v0.1)

v0.1 is for contributors. Install from source and run the test suite:

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

### Where this is going

This is the experience we are building towards (v0.2 to v0.4):

```bash
pip install turncoat-sdn
turncoat run --scenario on-off --strategy zt_sdn --seed 1 -o run.jsonl
turncoat score run.jsonl
turncoat compare --strategies zt_sdn,least_conn --seeds 30
```

## Release plan

| Release | Goal | Demo at the end |
|---|---|---|
| **v0.1** | The simulator runs on its own | `pytest` passes on a clean machine with no os-ken; one simulated run completes |
| v0.2 | One event format, scorers read it | `turncoat run` then `turncoat score` prints detection results |
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
|   `-- cli.py        # turncoat run / score / validate / compare
|-- backends/mininet/ # optional live testbed (v1.0)
|-- examples/         # custom scenario, strategy and attack (v1.0)
|-- docs/             # documentation set
|-- tests/
`-- .github/          # CI workflow, PR and issue templates
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. It
covers branch names, commit style, the review rota and the definition of done.
Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Origin

turncoat-sdn is carved out of our final-year project, *Zero Trust–Enabled SDN
Architecture for Secure and Intelligent Load Balancing in Edge Networks*, at
the Department of Computer Science and Engineering, Amrita Vishwa Vidyapeetham,
Coimbatore, under the guidance of Dr. Radhika N.

## Team

| Handle | Name | Track |
|---|---|---|
| bv | Bhuvanesh S | Simulator |
| arj | Arjun Krishnakumar | Event format and live recording |
| ash | Ashwin Kumar RM | Trust model and attacks |
| arv | Aravind Kumar M | Strategies, scoring and statistics |
| jv | K R Jeevan Raj | Repo, CLI, tests and release |

## License

[MIT](LICENSE)
