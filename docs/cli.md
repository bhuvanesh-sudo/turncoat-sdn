# Command line

**Owner:** jv · **Written in:** v0.2, extended through v0.4

## What it is

The `turncoat` command, and every option it takes. It joins the simulator,
the trust model, the event format and the scorers into one workflow:

| Command | What it does | Since |
|---|---|---|
| `turncoat run` | Simulates one seeded run and records it to `events.jsonl` | v0.2 |
| `turncoat validate` | Checks recordings against the event schema | v0.2 |
| `turncoat score` | Grades a recording: who was caught, how fast, at what cost | v0.2 |
| `turncoat compare` | Paired statistics over many seeds | v0.4 (planned) |

## Why it exists

Every piece of the benchmark works from Python, but joining them takes a
dozen lines: pick a router, pass the trust model and the latency tell, open
an `EventWriter`, then hand the file to the right scorer. The command line
does that the same way every time, so two people comparing results know
they ran the same thing.

## How to use it

Install the package (see [INSTALL.md](../INSTALL.md)), then:

```bash
turncoat run -o run.jsonl
turncoat validate run.jsonl
turncoat score run.jsonl
```

`run` prints where the file went and what to do next:

```
Recorded run.jsonl (15,598 lines, valid)
  zt_sdn on both, seed 1: 7,624 tasks, 11.6% SLO violations, first isolation at 3 s
Next: turncoat score run.jsonl
```

`score` answers the benchmark's three questions:

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

Run the same seed with a trust-blind strategy to see what the defence buys:

```bash
turncoat run --strategy round_robin -o rr.jsonl
turncoat score rr.jsonl
```

The controller still names and flags both attackers 3 seconds in, but
`round_robin` ignores the verdict: 928 tasks are still routed to each
attacker afterwards, and a quarter of all traffic lands on them.

If `turncoat` is not on your path (the virtual environment is not active),
`python -m turncoat_sdn.cli` does the same thing.

### `turncoat run`

Simulates one seeded run and records it.

| Option | Default | Meaning |
|---|---|---|
| `--strategy NAME` | `zt_sdn` | `random`, `round_robin`, `least_conn`, `no_trust` or `zt_sdn` (see [strategies.md](strategies.md)) |
| `--scenario NAME` | `both` | `clean` (no attacker), `sybil`, `drop`, `both` or `grayhole` (see [simulator.md](simulator.md) and [attacks.md](attacks.md)) |
| `--seed N` | `1` | Fixes the workload and every random choice. Same seed, same file, byte for byte. |
| `--duration SECONDS` | `120` | Simulated time |
| `-o`, `--output PATH` | `run.jsonl` | Where to write the recording. Folders are created; an existing file is overwritten. |
| `-q`, `--quiet` | off | Print nothing unless something goes wrong |

Every run gets the same controller view, whatever the strategy: the real
trust calculator and the Sybil latency tell. Strategies differ only in what
they do with it. The same seed hands every strategy the same arrivals and
service times, so two runs with one seed form a fair pair.

`run` validates the file it wrote before reporting success. A recording that
fails is a bug in the benchmark, and the command says so.

### `turncoat validate`

```bash
turncoat validate RECORDING [RECORDING ...] [--max-problems N]
```

Prints one verdict per file. An invalid file lists each problem with its line
number, up to `--max-problems` (default 20). The checks and messages are the
same as `python -m turncoat_sdn.events.validate`; the rules are in
[event-format.md](event-format.md).

### `turncoat score`

```bash
turncoat score RECORDING [--json] [--detail] [--slo-ms MS] [--window-cycles N] [--skip-validation]
```

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Print the scores as JSON instead of the summary |
| `--detail` | off | Also print the full attack report: per-subject table, confusion matrix and per-class metrics |
| `--slo-ms MS` | the recording's, else 500 | Deadline for an SLO violation |
| `--window-cycles N` | 120 | The attack classifier's evidence window, in poll cycles |
| `--skip-validation` | off | Score a recording even if it fails validation |

`score` validates the recording first and refuses an invalid one, because a
score built on a broken file is worse than none. It needs a `topology` event:
the ground truth is what it scores against.

What each number means:

| Section | Number | Computed from |
|---|---|---|
| Service | Tasks offered | `route` plus `route_denied` events |
| Service | Completed, failed | `report` events: `success` against everything else, plus every denial |
| Service | SLO violations | Failures, plus successes slower than the deadline |
| Service | Latency, mean / p95 | `latency_ms` of successful reports |
| Service | Routed to attackers | Share of `route` events whose `chosen` server is an attacker in the ground truth |
| Attackers | Named correctly / right family / missed | The attack classifier's verdict, from `turncoat_sdn.scoring.attack_report` |
| Attackers | Detected after onset | First correct label, minus the onset in the ground truth |
| Attackers | Flagged for quarantine | First `quarantine` event, minus the onset |
| Attackers | Traffic after that | `route` events to the server at or after its first `quarantine` |

The service totals count exactly what the simulator counts, so for a
simulated run they equal its `RunResult` (a test checks every strategy and
scenario). The scorers themselves are described in [scoring.md](scoring.md).

`--json` prints four keys: `recording` (the header), `service`, `detection`
(the counts in the last line of the summary) and `subjects` (one row per
server or device). Keys are sorted and floats rounded to 6 places, so the
output of one seed is identical on every machine. That is what
`tests/cli/golden_scores.json` pins.

### Exit status

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | The answer is no: a recording is invalid, or has no ground truth to score |
| 2 | A file could not be read or written, or the options were wrong |

## How it works inside

`src/turncoat_sdn/cli/` is a small package, one module per command:

| Module | Holds |
|---|---|
| `__init__.py` | The top-level parser and `main`, the `turncoat` entry point |
| `routers.py` | The five strategies as simulator routers, copied line for line from the final-year project's `evaluation/baseline.py` |
| `run.py` | `record_run`, which joins the router, `SimTrustModel`, the latency tell and an `EventWriter` |
| `validate.py` | A front end to `turncoat_sdn.events.validate` |
| `score.py` | Service totals from events, then the NFR, availability and attack scorers |
| `common.py` | The exit codes |

The CLI is the one place allowed to wire packages together (see
[architecture.md](architecture.md)). It adds no logic of its own to the
simulation: `tests/cli/test_routers.py` drives its routers against both
golden files from the final-year project, and they match to the last digit.

## Known limits

- `run` covers the five built-in scenarios. The `--scenario` choices grow
  with the attack catalogue in v0.3. There is no `--attack` or onset option
  yet, so a delayed onset needs Python (see [attacks.md](attacks.md)).
- The routers live in `cli/routers.py` because `turncoat_sdn.strategies`
  does not yet speak the simulator's router interface. When it does, the CLI
  should use it and this table should move.
- `score` grades one recording. Comparing strategies over many seeds, with
  p-values and confidence intervals, is `turncoat compare` in v0.4.
- `--slo-ms` changes the deadline for scoring only. The simulator's own
  `slo_violation_rate` in the `run` summary always uses the recorded deadline.
