# Event format

**Owner:** arj · **Written in:** v0.2, extended in v0.4 and v1.0

## What it is

`events.jsonl` is the one file format every part of turncoat-sdn agrees on.
A run, simulated or live, is recorded as one JSON object per line, appended in
time order. Every scorer reads that file. This page lists every line a
recording can hold and every field the scorers rely on. It is the contract
between whatever produces runs and whatever grades them.

The schema is versioned. This page describes **schema 1.0**, the version that
`turncoat_sdn.events.SCHEMA_VERSION` stamps into every recording.

## Why it exists

The final-year project already recorded its runs this way. The controller's
event bus appended every routing decision, outcome, classification and
quarantine to `data/events.jsonl`, and the evaluation scripts read the file
back. The format was never written down, though. Fields were added as each
dashboard panel or report needed them, and the only definition of an event
was the `publish()` call that produced it.

That is fine for one system, but a benchmark needs more. If the simulator, the
live testbed and someone else's controller all write the same file, the same
scorers grade all three, and their results can be compared. That only works
if the format is fixed, versioned and checkable, so this page writes it down
and `turncoat_sdn.events.validate` checks recordings against it.

## How to use it

### Write a recording

`EventWriter` writes the header for you, then one line per `write()` call.
`ts` is seconds since the run started.

```python
from turncoat_sdn.events import EventWriter

with EventWriter("run.jsonl", backend="sim", seed=7, strategy="zt_sdn", scenario="on-off") as rec:
    rec.write(
        "topology",
        0.0,
        graph={
            "nodes": [
                {"id": "srv1", "kind": "server", "attack": "none"},
                {"id": "srv3", "kind": "server", "attack": "on_off", "attack_start_s": 120.0},
            ],
            "links": [],
        },
    )
    rec.write("route", 121.4, chosen="srv3", task=5812)
    rec.write("classification", 135.9, subject="srv3", kind="node", attack_type="on_off")
    rec.write("quarantine", 136.0, node="srv3")
```

The file is line-buffered, so a run killed with Ctrl-C still leaves every
event it wrote. The writer refuses `NaN` and infinities, because standard JSON
has no way to spell them.

### Read a recording

```python
from turncoat_sdn.events import read_events

events = read_events("run.jsonl")  # a list of dicts, header first
```

`read_events` skips blank and malformed lines, so a recording whose last line
was cut off mid-write still scores. If you want to know whether the file is
actually well formed, validate it.

### Validate a recording

```bash
python -m turncoat_sdn.events.validate run.jsonl
```

```
run.jsonl: valid, schema 1.0, 12 lines
```

A broken recording lists each problem with its line, the event type and the
field involved. The exit code is 1:

```
broken_run.jsonl: 5 problems
  line 2 (topology): 'graph.nodes[1].attack_start_s' is required: "srv2" attacks ("grayhole"), and detection latency is measured from its onset
  line 3 (route): 'chosen' names "srv9", which is not a server in the topology
  line 4 (report): 'status' must be one of success, timeout, failure; got "ok"
  line 5 (report): ts 3.9 is earlier than 4.5 on line 4; events must be appended in time order
  line 6: not valid JSON: Unterminated string starting at column 51
```

Both files are in `tests/events/`. From Python, `validate_file(path)` and
`validate_events(events)` return a `Report` with `.ok`, `.problems` and
`.format(name)`. `turncoat validate` wraps the same call (see
`docs/cli.md`).

## How it works inside

### The shape of a recording

```
line 1   header        schema_version, backend, seed, strategy, scenario
line 2   topology      the roster and the ground truth: who attacks, from when
line 3+  everything else, in time order: route, report, anomaly, quarantine, ...
```

Three rules hold for the whole file:

1. **The header comes first, and only once.** It is the only line without a
   `ts`.
2. **The topology comes right after the header, and only once.** Every later
   event refers to its nodes, so a `route` naming `srv6` can be checked
   against the roster. One recording holds one run.
3. **`ts` never goes back.** Equal timestamps are fine (one poll's `anomaly`
   and `node_status` share one).

Fields this page does not list are allowed and ignored, and so are event types
it does not list. A live run records `switch_up`, `flow_install`, `block` and
more, and a recording stays valid if it carries them. They only need a `type`
and a `ts`.

### Value types

| Type | Accepts |
|---|---|
| string | A non-empty JSON string |
| number | A finite JSON number. `true`/`false` are not numbers, and `NaN`/`Infinity` are not JSON |
| non-negative number | A number that is 0 or more |
| integer | A JSON number with no fractional part |
| object, array | A JSON object or array |

### `header`

The first line. It says which schema the file follows and how the run was
made, so a scorer can refuse a file it cannot read.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | string | yes | Always `header` |
| `schema_version` | string | yes | `"1.0"` for files written now. Readers accept any `1.x`; a `2.0` file is refused |
| `backend` | `sim` or `live` | yes | Whether the simulator or a live testbed produced the run |
| `seed` | integer or null | no | The run's seed. Paired runs share one |
| `strategy` | string | no | The load-balancing strategy, for example `zt_sdn` |
| `scenario` | string | no | The scenario name, for example `on-off` |

### Fields on every other event

| Field | Type | Meaning |
|---|---|---|
| `type` | string | The event type, one of the sections below or any other name |
| `ts` | non-negative number | Seconds since the run started |

### `topology`

The roster and the ground truth. The simulator knows which nodes attack and
when they turn, and it writes that here. A scorer can then say "caught 14 s
after onset" rather than just "quarantined srv3".

| Field | Type | Required | Meaning |
|---|---|---|---|
| `graph` | object | yes | Holds `nodes` and, optionally, `links` |
| `graph.nodes` | array | yes | At least one node, and at least one with kind `server` |
| `graph.links` | array | no | Links between nodes, for drawing. Not read by the scorers |

Each node:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique within the topology, for example `srv3` or `iot12` |
| `kind` | string | yes | `server` and `iot` carry ground truth. Other kinds, such as `edge_switch`, do not |
| `attack` | string | on `server` and `iot` | The ground-truth attack, or `"none"` for an honest node |
| `attack_start_s` | non-negative number | when `attack` is not `"none"` | The onset, in seconds since the run started. Detection latency is measured from here |
| `ip` | string | no | An IoT node's address. The attack scorer uses it to map client-side evidence back to the device |

The onset is required for every attacker. Without it, the only way to measure
detection latency would be from the first anomaly, which makes every detector
look instant.

### Events the scorers read

Field names follow what the final-year project's controller recorded, so its
recordings need only a header and run-relative timestamps to validate.

#### `route`: a task sent to a server

| Field | Type | Required | Meaning |
|---|---|---|---|
| `chosen` | string | yes | The server that won. Must be a server in the topology |
| `task` | integer | no | Task id. Joins a `route` to its `report` in simulated runs |
| `client_ip` | string | no | The requesting client |
| `edge_score` | number or null | no | The winner's EdgeScore |
| `decision_ms` | non-negative number | no | Time taken to decide, for the routing-latency NFR |

#### `route_denied`: a request refused

| Field | Type | Required | Meaning |
|---|---|---|---|
| `reason` | string | yes | Why, for example `all candidates quarantined` |
| `client_ip` | string | no | The refused client |

#### `report`: a task's outcome

| Field | Type | Required | Meaning |
|---|---|---|---|
| `node` | string | yes | The server that handled it |
| `status` | `success`, `timeout` or `failure` | yes | What the client saw |
| `latency_ms` | non-negative number | yes | Time to the outcome |
| `task` | integer | no | Task id, matching the `route` |
| `device` | string | no | The reporting IoT device |
| `charged` | boolean | no | `false` when the outcome was not held against `node` (the task was re-steered onto it by a quarantine) |

#### `anomaly`: a detector flagged a server this poll

| Field | Type | Required | Meaning |
|---|---|---|---|
| `node` | string | yes | The flagged server |
| `signals` | object | yes | Signal name to strength, for example `{"packet_drop": 0.4}`. Every value is a number |
| `reasons` | array | no | Human-readable explanations |
| `anomaly` | number | no | The smoothed anomaly score after this poll |

#### `node_status`: one poll cycle finished

| Field | Type | Required | Meaning |
|---|---|---|---|
| `nodes` | object | yes | Per-node state snapshot. May be empty |

The attack scorer uses `node_status` as the cycle boundary. A poll without an
`anomaly` for a node counts as a clean observation of that node.

#### `classification`: the system names a subject's attack

| Field | Type | Required | Meaning |
|---|---|---|---|
| `subject` | string | yes | A server id, or a client's IP or device id |
| `kind` | `node` or `client` | yes | What the subject is |
| `attack_type` | string or null | yes | The label. `null` means the classifier withdrew its opinion |
| `confidence` | number | no | The classifier's confidence |

#### `quarantine` and `recovered`: a server isolated or readmitted

| Field | Type | Required | Meaning |
|---|---|---|---|
| `node` | string | yes | The server |
| `trust` | number | no | Its trust score at that moment |
| `anomaly` | number | no | Its anomaly score at that moment |

#### `reroute`: a client moved off a quarantined server

| Field | Type | Required | Meaning |
|---|---|---|---|
| `from_node` | string | yes | The quarantined server |
| `to_node` | string | yes | Where the client went |
| `client_ip` | string | no | The moved client |

#### `flood`: a client's request rate tripped the flood tell

| Field | Type | Required | Meaning |
|---|---|---|---|
| `client_ip` | string | yes | The client |
| `ratio` | number or null | no | Measured rate as a multiple of the expected rate |
| `rate_hz` | non-negative number | no | Measured requests per second |

#### `auth_denied`: a device failed authentication

| Field | Type | Required | Meaning |
|---|---|---|---|
| `device_id` | string | yes | The identity it claimed |
| `source_ip` | string | no | The host that actually sent the request. The attack scorer keys on this, so a spoofer is not filed under its victim |
| `kind` | string or null | no | `ip_pin` (correct key, wrong host) or `bad_response` (key not held) |

### Live-only events: `flow_stats` and `port_stats`

Data-plane counters that only a live backend can produce. They are checked
when present and never required.

| Event | Field | Type | Meaning |
|---|---|---|---|
| `flow_stats` | `dpid` | integer | The switch |
| `flow_stats` | `rules` | array | One entry per flow rule, with packet and byte counters |
| `port_stats` | `dpid` | integer | The switch |
| `port_stats` | `ports` | array | One entry per port, with traffic counters |

**Open question for the team:** should these stay in the core schema or move
to an optional live-only extension? The plan leaves it to the v0.2 kickoff.
Until that is decided, they sit in their own table
(`LIVE_EVENT_FIELDS` in `turncoat_sdn/events/schema.py`), so either answer is
a small change.

### Versioning

`schema_version` is `major.minor`.

- A **minor** bump (`1.1`) may add optional fields or new event types. Every
  `1.x` reader still reads it, and the validator accepts it.
- A **major** bump (`2.0`) may rename, remove or retype a field, or make a new
  field required. Readers refuse other majors rather than misreading them.

The schema is declared as data in `turncoat_sdn/events/schema.py`. The
validator checks against those tables, and a test fails if a type or field
there is missing from this page.

### Results files

A recording is one run. A comparison is many, and `turncoat replicate`
writes them as one **results file**: a CSV with a header row and one row per
run, every metric a column. `turncoat compare` and the statistics in
[statistics.md](statistics.md) read it, and so can a spreadsheet. This
section describes **results format 1.0**, `turncoat_sdn.stats.RESULTS_VERSION`.

```bash
turncoat replicate --strategies zt_sdn,round_robin --scenarios both --seeds 30 -o results.csv
```

```python
from turncoat_sdn.stats import read_results, write_results

rows = read_results("results.csv")  # typed: int counts, float rates, None for blanks
write_results(rows, "copy.csv")  # the same file back
```

Columns, in order (`turncoat_sdn.stats.RESULTS_FIELDS`):

| Column | Type | Blank when | Meaning |
|---|---|---|---|
| `strategy` | text | never | Strategy label, such as `zt_sdn` |
| `scenario` | text | never | Scenario name, such as `both` |
| `seed` | integer | never | The run's seed. The same seed gives every strategy the same workload. |
| `offered` | integer | never | Tasks offered |
| `completed` | integer | never | Tasks that finished |
| `failed` | integer | never | Timed out, gave up in a backlog, or refused because every server was quarantined |
| `slo_violation_rate` | float, 0 to 1 | never | Failures plus completions slower than the deadline, over offered |
| `failure_rate` | float, 0 to 1 | never | `failed` over `offered` |
| `malicious_share` | float, 0 to 1 | never | Share of tasks routed to an attacker after its onset |
| `mean_latency_ms` | float | never | Mean latency of completed tasks |
| `p95_latency_ms` | float | never | 95th-percentile latency of completed tasks |
| `gini` | float, 0 to 1 | never | How unevenly tasks were spread over servers |
| `time_to_isolate_s` | float | nothing was isolated | First poll at which every attacker had turned and was excluded |
| `attackers` | integer | never | Attacking servers and devices in the ground truth |
| `attackers_named` | integer | never | Of those, how many the attack scorer named with their exact label |
| `detection_rate` | float, 0 to 1 | no attacker | `attackers_named` over `attackers` |
| `mean_detection_latency_s` | float | no attacker named | Mean seconds from onset to the first correct label, over named attackers |
| `honest_subjects` | integer | never | Honest servers and devices scored |
| `honest_mislabelled` | integer | never | Of those, how many were given an attack label |
| `false_positive_rate` | float, 0 to 1 | no honest subject | `honest_mislabelled` over `honest_subjects` |

The first thirteen columns are the simulator's own row
(`turncoat_sdn.sim.CSV_FIELDS`, written by `sim.write_csv`); a test keeps the
two in step. The rest come from scoring the run's recording exactly as
`turncoat score` does. A blank cell means the run could not measure that
metric, never zero, and readers must skip it rather than average it in.
Rates are rounded to 6 places and latencies to 3, so one seed gives the same
file on every machine. Rows are ordered by scenario, then seed, then strategy.

`--summary PATH` also writes the intervals `replicate` prints, one row per
strategy, scenario and metric: `strategy`, `scenario`, `metric`, `runs`, `n`
(runs that measured it), `mean`, `ci_low`, `ci_high`, `confidence` and
`resamples`.

**Versioning.** A minor version (`1.1`) may only add columns at the end; a
reader looks columns up by name, and `read_results` keeps unknown trailing
columns as text. A major version may rename, remove or retype a column, and
`read_results` refuses a file whose header does not start with the 1.0
columns.

### Live runs

A live run is recorded in the same schema as a simulated one, with
`backend: live` in the header, and scored with the same commands:

```bash
turncoat validate live.jsonl
turncoat score live.jsonl
```

**The live backend records it directly.** `backends/mininet/` (see its
README) writes with `EventWriter`, stamps `ts` as seconds since the run's
shared start, and stamps and writes under one lock, so its lines never go
back in time. Its header adds `network` (`mininet` or `loopback`). Live
events carry every field the simulator's do, plus a few of their own:
`client_ip` on `route`, `device` on `report` and `poll_ms` on `node_status`.

**Where the IoT clients fit.** The IoT clients write no file of their own.
Each client sends its outcome to the controller, and the controller records it
as a `report` event, beside its own `route`, `anomaly` and `quarantine`
events. So a live run has exactly one recording, and its client outcomes have
the same `report` fields as the simulator's.

`backends/mininet/tests/test_live_recording.py` is the check: it records a
loopback run, passes it through `turncoat validate` and `turncoat score`, and
compares its events field by field with a simulated run of the same scenario.

**Convert an old recording.** The final-year controller's recordings convert
with `turncoat convert` (see [cli.md](cli.md#turncoat-convert)) or
`turncoat_sdn.events.convert_live_file(source, target)`:

```bash
turncoat convert data/events.jsonl -o live.jsonl --strategy zt_sdn
turncoat score live.jsonl
```

| The final-year recording | The converted one |
|---|---|
| No header | A header with `backend: live`, `started_at` and whatever `--seed`, `--strategy` and `--scenario` say |
| `ts` is wall-clock time | `ts` counts from the earliest stamp in the file, rounded to microseconds as the simulator rounds |
| Lines can be slightly out of time order, because the bus stamped `ts` before taking its lock and wrote after releasing it | Events sorted by `ts`; equal stamps keep their order in the file |
| The `topology` may be stamped after an early `switch_up` | The `topology` comes first, at `ts` 0 |
| Every event has a `seq` | `seq` is dropped |
| `NaN` or `Infinity` where a value was missing | `null` |
| A truncated tail line from Ctrl-C | Left out |

Everything else is kept as it is, extra fields and live-only event types
included. The converter refuses a file that already has a header, a file with
no `topology` (the start of the run is missing, and with it the ground
truth), and a file with more than one `topology` (one per controller start,
so two runs in one file). It counts and reports every change it makes.

`tests/events/fyp_live_run.jsonl` is a short recording in the final-year
controller's shape, with every one of the differences above.
`tests/events/test_live.py` converts it, and also takes simulated runs,
rewrites them in that shape, converts them back and checks that
`turncoat score` gives the same numbers to the last digit.

### What changed from the final-year project

| Final-year project | Schema 1.0 | Why |
|---|---|---|
| No header line | `header` first, with `schema_version` and `backend` | A reader can tell what it is reading and refuse what it cannot |
| `ts` was wall-clock time (`time.time()`) | `ts` is seconds since the run started | Runs compare on one timeline, and a simulator has no wall clock to give |
| Every event carried a `seq` counter for the dashboard's backfill | `seq` is optional and ignored | Line order already gives the sequence |
| Topology published once per controller start | Exactly one `topology`, right after the header | One recording is one run |
| Writer swallowed errors so the control plane never stalled | Writer raises on unwritable values | A benchmark recording that silently loses events is worse than one that fails |

## Known limits

- **References are checked against servers only.** A `classification` subject
  may be an IP address, and clients are not always in the topology, so client
  subjects are not cross-checked.
- **Unknown event types are not checked beyond `type` and `ts`.** That lets
  live recordings carry their extra events, but a typo in a type name (`qurantine`)
  passes validation and is silently ignored by the scorers.
- **Existing final-year recordings do not validate as they are.** They lack
  the header and use wall-clock `ts`. Run `turncoat convert` on them first
  (see [Live runs](#live-runs)).
- **A converted recording's `ts` is only as good as the controller's clock.**
  The final-year bus stamped wall-clock time, so a clock step during a run
  (an NTP correction) shows up in the converted `ts`. The live backend in
  `backends/mininet/` uses a monotonic clock and does not have this problem.
- **Ground-truth onsets in a converted recording are as configured, not as
  observed.** The final-year controller wrote each attacker's
  `attack_start_s` from its config, and each node agent counted that delay
  from its own start, which can be a few seconds after the controller's. So
  detection latency in a converted recording can read slightly long. The new
  live backend starts every process against one shared `t0` instead.
- **A results file carries no header line of its own.** Its version is
  implied by its columns. A run's backend and config are not in it; keep the
  command that produced it beside it, as [results.md](results.md) does.
