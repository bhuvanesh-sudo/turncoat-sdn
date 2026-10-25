# Tests

Run everything with `pytest` from the repository root. No os-ken, Mininet or
sudo is needed. Tests that need the live backend must be marked
`@pytest.mark.live` and skip themselves without it, so core CI passes them
over.

From v1.0, `pytest` also collects the live backend's own tests in
`backends/mininet/tests/` (listed in
[backends/mininet/README.md](../backends/mininet/README.md#tests)). They run
real agents and a real controller on 127.0.0.1 and need no Mininet either;
only `test_live_mininet.py` is `live`.

| File | What it guards |
|---|---|
| `test_package.py` | The package imports, every planned subpackage exists, and **no core module pulls in os-ken, Ryu or Mininet**. It walks every module, so it also covers modules added later. |
| `test_cli.py` | The `turncoat` entry point: `--version`, help and usage errors. |
| `cli/test_routers.py` | The CLI's five strategies reproduce both final-year golden files (`sim/golden_fyp_baseline.json`, `trust/golden_fyp_edge_score.json`). |
| `cli/test_run.py` | `turncoat run`: valid recordings, recording leaves the numbers unchanged, same seed gives the same file byte for byte, options and errors. |
| `cli/test_validate.py` | `turncoat validate`: verdicts and exit codes for valid, broken, missing and mixed files. |
| `cli/test_score.py` | `turncoat score`: service totals rebuilt from events equal the simulator's counts for every strategy and scenario, the attacker share equals the run's from each onset, detection and cut-off, `--json`, `--detail` and errors. |
| `cli/test_attack_option.py` | `turncoat run --attack`, `--onset` and `--identity-binding`: parsing every spec and its errors, where each attacker is placed, collisions refused with exit 2, and client rows and admission counts in `score`. |
| `cli/test_golden.py` | **Fixed seed, fixed scores**: `run` then `score --json` for eight cases must equal `cli/golden_scores.json`. |
| `sim/test_golden.py` | The simulator reproduces the final-year project's numbers exactly, from `sim/golden_fyp_baseline.json`. |
| `sim/test_simulator.py` | Seed pairing, attacker behaviour, queueing, the hooks, and CSV output. |
| `sim/test_recording.py` | Every scenario's `events.jsonl` recording validates, recording leaves the metrics unchanged, and the file agrees with the run: routes, outcomes, quarantines and one `node_status` per poll. |
| `trust/test_latency_tell.py` | The Sybil latency tell's scenarios from the final-year project, and that plugging it into the simulator reproduces the original `time_to_isolate_s`. |
| `trust/test_calculator.py` | The trust calculator (T-01 to T-07) and `SimTrustModel`, the adapter that plugs it into the simulator. |
| `trust/test_edge_selector.py` | EdgeScore, quarantine, power-of-two-choices, epsilon-exploration and the graduated-response bands. |
| `trust/test_liar_floor.py` | **The 0.44 liar floor**: a liar that serves well never drops below the isolation threshold, and only the anomaly gate catches it. |
| `trust/test_zt_sdn.py` | `no_trust` and `zt_sdn` reproduce the final-year project's numbers from `trust/golden_fyp_edge_score.json`, and detection tests E-08 to E-11. |
| `scoring/test_attack_classifier.py` | The attack classifier's rules: sybil vs on-off, blackhole vs grayhole, abstention, client labels. |
| `events/test_jsonl.py` | The JSONL writer and reader: header first, line-buffered, no interleaved lines under concurrent writers, and a truncated tail line skipped on read. |
| `events/test_validate.py` | **The event schema**: `sample_run.jsonl` passes, `broken_run.jsonl` fails with one clear message per problem, every rule in `docs/event-format.md`, and the doc lists every type and field in `events/schema.py`. |
| `scoring/test_attack_report.py` | Ground truth, cycle reconstruction, the confusion matrix and detection latency, the CLI, and a scored simulator run (the simulator's own recording, via `scoring/conftest.py`). |
| `attacks/test_profiles.py` | The attack interface on its own: honest before `start_s`, hostile after, settings and validation, and what `Sybil` and `Blackhole` do once they turn. |
| `attacks/test_grayhole.py` | The grayhole: drops its configured fraction, nothing before `start_s`, one seeded draw per task that leaves the workload paired, a recording that validates, the scorer naming it `grayhole` for `zt_sdn`, and the trust-only containment it cannot name. |
| `attacks/test_on_off.py` | The on-off attacker: phase timing, Sybil behaviour while hostile and honesty between, nothing before `start_s`, no draws and a paired workload, a recording that validates, the scorer naming it `onoff` for `zt_sdn` across seeds, onsets and phase lengths, and the phase lengths where it stops. |
| `attacks/test_spoof.py` | The identity spoof and the client attack interface: quiet until `start_s`, a fixed beat with no draws, the admission rules (`roster` refuses at any onset; `tofu` refuses once the victim has spoken and otherwise hands it the identity, live run 9), a refused spoof costing the fleet nothing, devices and refusals in the recording, and the scorer naming it `spoof` at its first attempt. |
| `attacks/test_onset.py` | Attacks in the simulator: passing them explicitly changes no number, onset is recorded in `topology`, turncoats are honest before it, malicious traffic and detection count from it, random attacks stay paired, and the late-blackhole result. |
| `benchmark/test_benchmark_scoring.py`, `benchmark/test_comparison_report.py`, `benchmark/test_strategy_benchmark.py` | The v0.3 strategy benchmark: per-strategy summaries, comparison reports in CSV and JSON, and the reproducible runner. |
| `stats/test_descriptive.py` | Descriptive statistics over repeated runs: mean, sample standard deviation, minimum, maximum and count. |
| `stats/test_bootstrap.py` | Percentile-bootstrap intervals: the method against a direct numpy computation, seeding, paired resampling across groups, blanks, one run and agreeing runs, bad input, the opt-in interval on `summarize_metrics`, and 95% coverage on skewed data. |
| `stats/test_replicates.py` | **The results file**: its columns start with the simulator's row, the detection columns, blanks for what a run cannot measure, and a writer and reader that round-trip with types. |
| `examples/test_custom_attack.py` | `examples/custom_attack.py` stays under 50 lines of code, its slowpoke is honest before onset and slow after, it costs SLO violations without being quarantined, and the script runs and records a recording that validates and scores. |
| `cli/test_compare.py` | `turncoat compare`: the CSV report and its errors, the comparison family equals `compare_strategies` when everything is measured and drops only cells no seed can measure, one Holm family across scenarios, the table's means, intervals and p-values come from `turncoat_sdn.stats`, **Better** follows each metric's direction, and a full default comparison no longer fails on `clean`. |
| `cli/test_replicate.py` | `turncoat replicate`: one row per paired run equal to `run` then `score`, every metric printed with an interval, the summary CSV, the same file for the same arguments, `--onset`, usage errors, and that the strategy benchmark runs every scenario. |
| `events/test_event_list.py` | `EventList`: a recording kept in memory equals the file read back. |
| `sim/test_recording.py`, `sim/test_golden.py` | Also guard `sim/detect.py`, the detection step shared with the live backend from v1.0: moving it out of the event loop changed no number. |
| `events/test_live.py` | **Live recordings**: `fyp_live_run.jsonl` (the final-year controller's shape) is invalid as written and valid once converted, every conversion rule and refusal, and simulated runs rewritten in that shape score identically once converted. |
| `backends/mininet/tests/test_live_recording.py` | **The live recording check**: a loopback live run passes `turncoat validate` and `turncoat score` unchanged, its events carry every field a simulated run's do, and the IoT clients' outcomes arrive as `report` events. |
| `cli/test_convert.py` | `turncoat convert`: converts, validates and points to `score`, header options, the converted fixture scores with the attacker named, refusals and exit codes. |

## Porting tests from the final-year project

Each move brings its tests with it, in the same pull request. The table maps
the original `tests/` files to the task that ports them. Fix import paths only
on the way over; if a number changes, the move is wrong, not the test.

| Original test file(s) | New home | Ported by | Release |
|---|---|---|---|
| `test_baseline.py` (simulator parts) | `tests/sim/` | bv | v0.1 |
| `test_trust.py`, `test_edge_selector.py`, `test_graduated_response.py` | `tests/trust/` (includes the 0.44 liar-floor test) | ash | v0.1 |
| `test_flow_monitor.py` (only `evaluate_latency_tell`, `fleet_latency_baseline`) | `tests/trust/` | arj | v0.1 |
| `test_baseline.py` (strategy parts) | `tests/strategies/` | arv | v0.1 |
| `test_event_bus.py` (JSONL writer/reader parts) | `tests/events/` | arj | v0.2 |
| `test_attack_classifier.py`, `test_attack_report.py` | `tests/scoring/` | ash | v0.2 |
| `test_nfr_report.py`, `test_interval_report.py`, `test_availability_report.py` | `tests/scoring/` | arv | v0.2 |
| `test_flood_detector.py`, `test_iot_client_flood.py`, `test_iot_client_spoof.py` | `tests/attacks/` | arv, jv | v0.3 |
| `test_stats.py` | `tests/stats/` | arv | v0.4 |
| `test_replicates.py` | `tests/stats/` | arj | v0.4 |
| `test_node_agent.py`, `test_run_demo_mininet.py`, `test_live_config_preflight.py` | `backends/mininet/tests/` (done: `test_node_agent.py`, `test_topology.py`) | bv | v1.0 |

Tests for the blockchain ledger, RAFT, PRESENT-80, dashboard and AI optimiser
stay in the final-year project. They are out of scope for this benchmark.
