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
| `turncoat replicate` | Runs many seeds per strategy and scenario into one results CSV, with a mean and confidence interval on every metric | v0.4 |
| `turncoat compare` | Compares strategies on matched seeds: a table of every metric with a paired bootstrap interval, Wilcoxon p-value and Holm-adjusted p-value; exports a CSV report | v0.4 |

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
| `--scenario NAME` | `both` | `clean` (no attacker), `sybil`, `drop`, `both`, `grayhole`, `onoff` or `spoof` (see [simulator.md](simulator.md) and [attacks.md](attacks.md)) |
| `--seed N` | `1` | Fixes the workload and every random choice. Same seed, same file, byte for byte. |
| `--duration SECONDS` | `120` | Simulated time |
| `--attack SPEC` | none | Adds an attacker to the scenario's. Repeatable. See [Adding attackers](#adding-attackers). Since v0.3. |
| `--onset SECONDS` | `0` | When the scenario's attackers, and any `--attack` without its own `start=`, turn. Since v0.3. |
| `--identity-binding RULE` | `roster` | How the controller binds IoT device ids to addresses, in a run with a client attacker: `roster` (provisioned) or `tofu` (first claim wins). See [attacks.md](attacks.md#identity-spoof). Since v0.3. |
| `-o`, `--output PATH` | `run.jsonl` | Where to write the recording. Folders are created; an existing file is overwritten. |
| `-q`, `--quiet` | off | Print nothing unless something goes wrong |

Every run gets the same controller view, whatever the strategy: the real
trust calculator and the Sybil latency tell. Strategies differ only in what
they do with it. The same seed hands every strategy the same arrivals and
service times, so two runs with one seed form a fair pair.

`run` validates the file it wrote before reporting success. A recording that
fails is a bug in the benchmark, and the command says so.

In a run with a client attacker, `run` also reports the admission check:
how many of the attackers' own requests it refused, and how many honest
requests it refused because another address held the sender's identity (only
possible under `tofu`).

#### Adding attackers

`--attack` takes an attack's name, then optional `key=value` settings,
separated by commas:

| Name | Attacker | Settings |
|---|---|---|
| `sybil`, `blackhole` (or `drop`), `grayhole`, `onoff` | A server | `node=srvN`: which server. Default: the highest-numbered one not already attacking. |
| `spoof` | An IoT device claiming another's identity | `client=iotN`: the spoofer, default `iot38`. `target=iotN`: whom it claims to be, default `iot1`. |
| Any | | `start=SECONDS`: its onset. Default: `--onset`, else 0. |

Each `--attack` adds one attacker to the scenario's own, built exactly as the
scenario of the same name builds it (the same `SimConfig` settings), so
`--scenario clean --attack spoof` is the `spoof` scenario. Two attackers on
the same server or device are refused, with exit status 2.

```bash
turncoat run --scenario clean --attack spoof,start=15 --attack sybil,node=srv3,start=30 -o mixed.jsonl
turncoat score mixed.jsonl
```

```
Attackers
  iot38    spoof      named correctly as spoof
           detected 0.0 s after onset
           53 requests refused at admission
  srv3     sybil      named correctly as sybil
           detected 2.0 s after onset
           flagged for quarantine 2.0 s after onset; no traffic after that

Detection: 2 of 2 attackers named correctly, 1 flagged, 1 cut off; 0 of 46 honest subjects mislabelled, 0 flagged.
Admission: 53 requests refused, 53 from attackers and 0 from honest devices.
```

A spoofer is stopped at admission, before routing, so it is never flagged
for quarantine or cut off: those two counts are about servers.

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
| Service | Routed to attackers | Share of `route` events whose `chosen` server is an attacker in the ground truth, counted from that attacker's onset |
| Attackers | Named correctly / right family / missed | The attack classifier's verdict, from `turncoat_sdn.scoring.attack_report` |
| Attackers | Detected after onset | First correct label, minus the onset in the ground truth |
| Attackers | Flagged for quarantine | First `quarantine` event, minus the onset |
| Attackers | Traffic after that | `route` events to the server at or after its first `quarantine` |
| Attackers | Refused at admission | An IoT client's `auth_denied` events, filed under the device that sent them (by `source_ip`), not the identity they claimed |
| Admission | Refused from attackers, from honest devices | The same, summed over attacking and honest devices. Printed only for a recording with IoT clients. |

The service totals count exactly what the simulator counts, so for a
simulated run they equal its `RunResult` (a test checks every strategy and
scenario). The scorers themselves are described in [scoring.md](scoring.md).

`--json` prints four keys: `recording` (the header), `service`, `detection`
(the counts in the last line of the summary) and `subjects` (one row per
server or device). In a recording with IoT clients, each client's row also
carries `refused_at_admission`, and `detection` carries `admission` with
`refused`, `refused_attackers` and `refused_honest`. Recordings without
clients keep exactly the v0.2 shape. Keys are sorted and floats rounded to 6 places, so the
output of one seed is identical on every machine. That is what
`tests/cli/golden_scores.json` pins.

### `turncoat replicate`

```bash
turncoat replicate [--strategies LIST] [--scenarios LIST] [--seeds N] [--first-seed SEED]
                   [--duration SECONDS] [--onset SECONDS] [-o PATH] [--summary PATH]
                   [--confidence LEVEL] [--resamples N] [-q]
```

Runs every chosen strategy on every chosen scenario over the same seeds,
scores each run, and writes one row per run to a results CSV. Then it prints
every metric's mean for each strategy and scenario with a percentile-bootstrap
confidence interval.

| Option | Default | Meaning |
|---|---|---|
| `--strategies LIST` | all five | Comma-separated, such as `zt_sdn,least_conn` |
| `--scenarios LIST` | all seven | Comma-separated, such as `both,grayhole` |
| `--seeds N` | `30` | Seeds per strategy and scenario |
| `--first-seed SEED` | `1` | Seeds run from here upward: `--seeds 30` is seeds 1 to 30 |
| `--duration SECONDS` | `120` | Simulated time per run |
| `--onset SECONDS` | `0` | When the scenarios' attackers turn |
| `-o`, `--output PATH` | `results.csv` | The results file. Folders are created; an existing file is overwritten. |
| `--summary PATH` | none | Also write every mean and interval to this CSV |
| `--confidence LEVEL` | `0.95` | Coverage of the intervals |
| `--resamples N` | `10000` | Bootstrap resamples per interval |
| `-q`, `--quiet` | off | Print nothing unless something goes wrong |

```
$ turncoat replicate --scenarios grayhole --seeds 5 -o r.csv
Ran 25 runs (5 strategies x 1 scenario x 5 seeds, 1 to 5) in 5 s
Wrote r.csv (25 rows, results format 1.0)

Mean over seeds, with 95% bootstrap confidence interval [low, high] (10,000 resamples)

grayhole  (5 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          19.58 [19.29, 19.86]     19.13 [18.84, 19.35]     23.42 [21.40, 25.17]     13.18 [12.70, 13.61]      10.00 [9.67, 10.34]
  Failed (%)                     9.27 [9.03, 9.51]        9.24 [8.94, 9.52]        3.95 [3.43, 4.47]        2.75 [2.61, 2.85]        0.10 [0.05, 0.15]
  ...
```

Each run gets the controller view `turncoat run` gives it, and the same seed
gives every strategy the same workload, so the rows are paired. Recordings
are kept in memory and scored there, so a full default comparison (1,050
runs) writes only the results and takes about three and a half minutes. The
same arguments give the same file byte for byte. The columns are described
in [event-format.md](event-format.md#results-files), the intervals in
[statistics.md](statistics.md#confidence-intervals), and a full run in
[results.md](results.md).

### `turncoat compare`

```bash
turncoat compare RESULTS.csv [--strategies LIST] [--scenarios LIST] [--metrics LIST]
                 [--alpha LEVEL] [--alternative two-sided|less|greater]
                 [--confidence LEVEL] [--resamples N] [-o PATH] [-q]
```

`replicate` puts an interval on each strategy's mean. `compare` answers the
question a reader actually asks: is the gap between two strategies real, or
one lucky set of workloads? It reads a results file, pairs every two chosen
strategies run for run on matched seeds, and prints one table per scenario
and pair, with a row per metric:

```
$ turncoat replicate --strategies zt_sdn,least_conn --scenarios both,clean --seeds 30 -q
$ turncoat compare results.csv
both: zt_sdn vs least_conn  (30 paired seeds)
                            zt_sdn   least_conn         Difference [95% CI]         p    Holm p   Better
  SLO violations (%)         12.09        38.19     -26.10 [-27.11, -25.12]   <0.0001   <0.0001   zt_sdn
  Failed (%)                  0.10        12.48     -12.37 [-12.95, -11.81]   <0.0001   <0.0001   zt_sdn
  Routed to attackers (%)     0.36        15.34     -14.98 [-15.98, -13.96]   <0.0001   <0.0001   zt_sdn
  Mean latency (ms)          243.6        461.1     -217.5 [-229.5, -206.1]   <0.0001   <0.0001   zt_sdn
  p95 latency (ms)           684.0       1696.8   -1012.8 [-1060.4, -962.7]   <0.0001   <0.0001   zt_sdn
  Load Gini                  0.257        0.134     +0.123 [+0.113, +0.133]   <0.0001   <0.0001   least_conn
  Time to isolate (s)          3.4          3.0           +0.4 [+0.3, +0.6]    0.0003    0.0019   least_conn
  Attackers named (%)       100.00       100.00        +0.00 [+0.00, +0.00]    1.0000    1.0000   -
  Detection latency (s)        3.2          3.1           +0.1 [-0.0, +0.3]    0.0377    0.1887   -
  Honest mislabelled (%)      0.00         0.00        +0.00 [+0.00, +0.00]    1.0000    1.0000   -

clean: zt_sdn vs least_conn  (30 paired seeds)
  ...

Not compared, because no seed measured them for both strategies:
  clean: time_to_isolate_s, detection_rate, mean_detection_latency_s

Difference: first strategy minus second on each seed, averaged, with a paired
  percentile bootstrap interval (10,000 resamples, seed 0).
p: two-sided Wilcoxon signed-rank test. Holm p: adjusted across all 17 tests above.
Better: the better strategy when Holm p <= 0.05; lower is better except for attackers named.

Wrote comparisons.csv (17 comparisons, 12 significant at alpha=0.05)
```

Under a Sybil and a blackhole, `zt_sdn` cuts SLO violations by 26
percentage points and sends 15 points less traffic to the attackers, and
every one of those intervals sits far from zero. It loses on load balance and
isolates 0.4 s later, because shunning attackers leaves honest servers
unevenly loaded. Detection latency shows Holm at work: a raw p of 0.038 looks
significant, but corrected across the 17 tests it is 0.19, and its interval
touches zero, so there is no winner.

| Option | Default | Meaning |
|---|---|---|
| `RESULTS.csv` | required | A results file from `turncoat replicate` (see [event-format.md](event-format.md#results-files)) |
| `--strategies LIST` | every one in the file | Comma-separated. Every pair is compared, so three strategies give three blocks per scenario. |
| `--scenarios LIST` | every one in the file | Comma-separated |
| `--metrics LIST` | all ten | Any of the results file's metric columns, such as `slo_violation_rate,malicious_share` |
| `--alpha LEVEL` | `0.05` | Significance level for **Better** and the report's `significant` column |
| `--alternative` | `two-sided` | `less` or `greater` test whether the first strategy's values are lower or higher |
| `--confidence LEVEL` | `0.95` | Coverage of the difference intervals |
| `--resamples N` | `10000` | Bootstrap resamples per interval |
| `-o`, `--output PATH` | `comparisons.csv` | The comparison report. Folders are created; an existing file is overwritten. |
| `-q`, `--quiet` | off | Print nothing unless something goes wrong. The report is still written. |

#### Reading the table

| Column | What it is |
|---|---|
| *first*, *second* | Each strategy's mean over the seeds where both measured the metric. Rates are percentages. |
| Difference [95% CI] | First minus second on each seed, averaged, with a paired percentile bootstrap interval from `turncoat_sdn.stats.bootstrap.paired_bootstrap_ci`. Rates are in percentage points. |
| p | Wilcoxon signed-rank test on the paired differences, from `turncoat_sdn.stats.paired_wilcoxon`. A metric on which the two never differ gets `1.0000`. |
| Holm p | `p` after Holm's correction across **every test in the table**: all metrics, pairs and scenarios together |
| Better | When Holm p is at most `--alpha`, the strategy with the better mean. Lower is better for every metric except attackers named. Otherwise `-`. |

A metric label ending in `, N pairs` was blank on some seeds (a run with no
attacker named has no detection latency), so its test used fewer pairs than
the block's seeds.

Why paired, why Wilcoxon and why Holm are in
[statistics.md](statistics.md) and [paired-statistics.md](paired-statistics.md).
One consequence is worth knowing before you choose `--seeds`: with N pairs
the smallest two-sided Wilcoxon p is 2/2^N. Four seeds can never get below
0.125, so `compare` on a quick four-seed run reports no winner however large
the gap. Thirty seeds leave plenty of room, even after Holm.

#### Metrics that cannot be compared

Some metrics are blank on every run of a scenario: there is no time to
isolate or detection rate in `clean`, where nobody attacks. A test with no
pairs is not a test, so `compare` leaves that scenario and metric out of the
Holm family and lists it under the table, rather than refusing the whole
comparison.

#### The report

`-o` writes one row per test with the columns in
`turncoat_sdn.stats.COMPARISON_FIELDS`: the two strategies, scenario, metric,
pair counts, Wilcoxon statistic, raw and Holm-adjusted p-values, mean and
median difference, alternative, alpha and whether it was significant. The
table and the report come from the same tests, in the same order. For the
intervals and effect sizes as JSON, use `turncoat evaluate`.

`compare` reads only the results file, so the same file gives the same table
and report every time.

### Exit status

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | The answer is no: a recording is invalid or has no ground truth to score, or a results file is invalid or cannot be compared |
| 2 | A file could not be read or written, or the options were wrong |

## How it works inside

`src/turncoat_sdn/cli/` is a small package, one module per command:

| Module | Holds |
|---|---|
| `__init__.py` | The top-level parser and `main`, the `turncoat` entry point |
| `routers.py` | The five strategies as simulator routers, copied line for line from the final-year project's `evaluation/baseline.py` |
| `run.py` | `record_run`, which joins the router, `SimTrustModel`, the latency tell and an `EventWriter` |
| `attack_spec.py` | Parses `--attack` and places each attacker beside the scenario's, built by the scenario of the same name |
| `validate.py` | A front end to `turncoat_sdn.events.validate` |
| `score.py` | Service totals from events, then the NFR, availability and attack scorers |
| `replicate.py` | `replicate_rows`, which runs and scores the paired grid into results rows, and the interval table |
| `compare.py` | `build_report`, which picks the tests and runs them through `turncoat_sdn.stats` as one Holm family, and the comparison table |
| `common.py` | The exit codes |

The CLI is the one place allowed to wire packages together (see
[architecture.md](architecture.md)). It adds no logic of its own to the
simulation: `tests/cli/test_routers.py` drives its routers against both
golden files from the final-year project, and they match to the last digit.

## Known limits

- `--attack` places attacks with the settings their scenario uses. To change
  how one behaves (a grayhole's drop fraction, a spoofer's interval), use
  Python and `SimConfig` (see [attacks.md](attacks.md#how-to-use-it)).
- `flood` is not an `--attack` choice until the flood attack lands in v0.3.
- The routers live in `cli/routers.py` because `turncoat_sdn.strategies`
  does not yet speak the simulator's router interface. When it does, the CLI
  should use it and this table should move.
- `score` grades one recording, `replicate` puts intervals on many, and
  `compare` tests the differences. `compare` needs every compared strategy
  run on the same seeds in each scenario, which `replicate` guarantees; a
  results file stitched together from different seed ranges is refused.
- `compare` tests every pair. Five strategies on seven scenarios is 700
  tests in one Holm family and 70 tables; pass `--strategies` and
  `--scenarios` to ask a narrower question with more power.
- `replicate` takes no `--attack` or `--identity-binding`: it runs the
  built-in scenarios as they are, so every row is a scenario anyone can
  reproduce by name. It also runs one run at a time, on one core.
- `--slo-ms` changes the deadline for scoring only. The simulator's own
  `slo_violation_rate` in the `run` summary always uses the recorded deadline.
