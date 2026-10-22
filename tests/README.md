# Tests

Run everything with `pytest` from the repository root. No os-ken, Mininet or
sudo is needed. Tests that need the live backend must be marked
`@pytest.mark.live`; core CI never runs them.

| File | What it guards |
|---|---|
| `test_package.py` | The package imports, every planned subpackage exists, and **no core module pulls in os-ken, Ryu or Mininet**. It walks every module, so it also covers modules added later. |
| `test_cli.py` | The `turncoat` entry point: `--version`, help and usage errors. |
| `sim/test_golden.py` | The simulator reproduces the final-year project's numbers exactly, from `sim/golden_fyp_baseline.json`. |
| `sim/test_simulator.py` | Seed pairing, attacker behaviour, queueing, the hooks, and CSV output. |
| `trust/test_latency_tell.py` | The Sybil latency tell's scenarios from the final-year project, and that plugging it into the simulator reproduces the original `time_to_isolate_s`. |
| `trust/test_calculator.py` | The trust calculator (T-01 to T-07) and `SimTrustModel`, the adapter that plugs it into the simulator. |
| `trust/test_edge_selector.py` | EdgeScore, quarantine, power-of-two-choices, epsilon-exploration and the graduated-response bands. |
| `trust/test_liar_floor.py` | **The 0.44 liar floor**: a liar that serves well never drops below the isolation threshold, and only the anomaly gate catches it. |
| `trust/test_zt_sdn.py` | `no_trust` and `zt_sdn` reproduce the final-year project's numbers from `trust/golden_fyp_edge_score.json`, and detection tests E-08 to E-11. |
| `scoring/test_attack_classifier.py` | The attack classifier's rules: sybil vs on-off, blackhole vs grayhole, abstention, client labels. |
| `scoring/test_attack_report.py` | Ground truth, cycle reconstruction, the confusion matrix and detection latency, the CLI, and a scored simulator run (recorded by `scoring/conftest.py`). |

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
| `test_node_agent.py`, `test_run_demo_mininet.py` | `backends/mininet/tests/` | bv | v1.0 |

Tests for the blockchain ledger, RAFT, PRESENT-80, dashboard and AI optimiser
stay in the final-year project. They are out of scope for this benchmark.
