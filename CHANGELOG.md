# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every pull request adds one line under **Unreleased**, in the section that
fits (Added, Changed, Fixed, Removed).

## [Unreleased]

### Added

- Replicate results file in `turncoat_sdn.stats.replicates`: one CSV row per
  run with strategy, scenario, seed and every metric, simulator and detection
  columns alike (results format 1.0, `RESULTS_FIELDS`), with a typed reader;
  `turncoat replicate` runs every strategy on every scenario over N paired
  seeds into it in one command, scoring recordings kept in memory by the new
  `turncoat_sdn.events.EventList`; the results-file section of
  `docs/event-format.md` and `docs/cli.md`.
- Bootstrap confidence intervals in `turncoat_sdn.stats.bootstrap`: seeded
  percentile bootstrap with configurable confidence and resamples, paired
  across strategies; `turncoat replicate` prints every metric's mean with
  `[low, high]` and writes them with `--summary`, and
  `summarize_metrics(..., confidence=0.95)` adds them to descriptive
  summaries; `docs/statistics.md` (confidence intervals) and
  `docs/results.md`, a full 30-seed comparison.


### Fixed

- The strategy benchmark runner's default scenarios were a fixed list of the
  four v0.2 scenarios, missing `grayhole`, `onoff` and `spoof`; it now uses
  `turncoat_sdn.sim.SCENARIOS`.

## [0.3.0] - 2026-10-25

### Added

- Attack profile interface in `turncoat_sdn.attacks`: `ServerAttack` keeps a
  server honest until its `start_s` onset, and the simulator's Sybil and
  blackhole moved out of its event loop onto it as `Sybil` and `Blackhole`
  with every golden number unchanged. `SimConfig.attack_start_s` delays a
  scenario's attackers, `simulate(attacks=...)` places your own, each
  attacker gets its own seeded random stream, and the `topology` event records
  every onset; malicious traffic and isolation now count from the onset.
  Tests, and `docs/attacks.md` with how to write an attack (ash).
- Grayhole attack, `Grayhole` in `turncoat_sdn.attacks`: drops a configurable
  fraction of tasks after its onset (`drop_fraction`, default 0.5), one seeded
  draw per task; a `grayhole` scenario, also a `turncoat run --scenario`
  choice, with `SimConfig.grayhole_drop_fraction`; tests that the fraction is
  honoured, nothing drops before onset, recordings validate and the scorer
  names it; its entry in `docs/attacks.md` (bv).
- On-off attack, `OnOff` in `turncoat_sdn.attacks`: lies like the Sybil for
  `on_s`, is honest for `off_s`, and repeats from its onset (default 10 s
  each); an `onoff` scenario and `turncoat run --scenario` choice with
  `SimConfig.onoff_on_s` and `onoff_off_s`; tests of phase timing, onset,
  pairing, recording and that the scorer names it, with the phase lengths
  where it stops; its entry in `docs/attacks.md` (arj's task, written by bv).
- Identity spoof, `IdentitySpoof` in `turncoat_sdn.attacks`, on a new
  `ClientAttack` interface for attacks by IoT devices: from its onset a
  device claims another's identity from its own address every 2 s. Runs with
  a client attacker model the 40 IoT devices and the controller's admission
  check, ported from the project's `IdentityBinding` with a `roster` or
  `tofu` rule (`SimConfig.identity_binding`); refusals are recorded as
  `auth_denied`, and runs without one are unchanged. A `spoof` scenario
  (`iot38` as `iot1`), `simulate(client_attacks=...)`, and tests that the
  roster refuses it at any onset and costs the fleet nothing, that `tofu`
  reproduces live run 9, and that the scorer names it `spoof`; its entry in
  `docs/attacks.md` (jv).
- `turncoat run --attack SPEC` adds attackers beside the scenario's
  (`spoof,client=iot38,target=iot1,start=15`, `sybil,node=srv3`), `--onset`
  delays them, and `--identity-binding` picks the admission rule; `run`
  reports admission refusals, and `score` reports each IoT client's refused
  requests and an admission total; `docs/cli.md` (jv).
- Descriptive strategy benchmark: per-strategy summaries in
  `turncoat_sdn.scoring.benchmark`, a reproducible comparison runner in
  `scoring.strategy_benchmark`, comparison reports in
  `scoring.comparison_report`, and grouped descriptive statistics in
  `turncoat_sdn.stats.descriptive`; `docs/benchmark-statistics.md` (arv).

### Fixed

- `turncoat score` counted traffic to an attacking server from the start of
  the run; "Routed to attackers" now counts from each attacker's onset, and
  equals the simulator's `malicious_share`. Runs with an onset of 0 are
  unchanged (jv).

## [0.2.0] - 2026-10-23

### Added

- Attack scoring in `turncoat_sdn.scoring`: the attack classifier and attack
  report moved from the final-year project, printing a confusion matrix,
  per-class metrics and detection latency for a recording; tests including a
  scored simulator run, and the attack scoring section of `docs/scoring.md`
  (ash).
- Event schema 1.0 for `events.jsonl` in `turncoat_sdn.events`: a
  `schema_version` header line, the JSONL writer and reader ported from the
  project's `event_bus.py` and `load_events`, a validator with line-numbered
  messages (`python -m turncoat_sdn.events.validate`), and
  `docs/event-format.md` (arj).
- The simulator records runs to `events.jsonl`: a `recorder` hook on
  `simulate` and a `recorders` factory on `run_paired` that take arj's
  `EventWriter`, writing the topology with ground truth, every route and
  outcome, anomaly signals, quarantines and a per-poll `node_status`; every
  scenario's recording validates and recording leaves the metrics unchanged.
  The attack scoring tests now score this recording. Recording section in
  `docs/simulator.md` (bv).
- `turncoat run`, `validate` and `score` commands: `run` records one seeded
  run of any of the five strategies, `validate` checks recordings against the
  schema, and `score` reports service cost, attacker detection and isolation
  latency, and traffic still routed to flagged attackers, as a summary or
  stable `--json`. The CLI's routers reproduce both final-year golden files,
  rebuilt service totals equal the simulator's counts, and a golden-file test
  pins the scores of eight fixed-seed runs; `docs/cli.md` (jv).

## [0.1.0] - 2026-10-23

### Added

- Repository scaffold: `src/` package layout with the `sim`, `attacks`,
  `strategies`, `trust`, `events`, `scoring` and `stats` subpackages, a
  `turncoat` console entry point, CI on a plain runner, PR and issue
  templates, `README.md` and `CONTRIBUTING.md` (jv).
- Seeded simulator in `turncoat_sdn.sim`, ported from the final-year
  project's `evaluation/baseline.py` with routing, trust and the latency tell
  as hooks; golden-file tests against the original numbers,
  `docs/simulator.md` and `INSTALL.md` (bv).
- Latency tell (`fleet_latency_baseline`, `evaluate_latency_tell`) moved out of
  the project's os-ken-bound `controller/flow_monitor.py` into
  `turncoat_sdn.trust.latency_tell`, so no core module imports os-ken; its
  tests and `docs/architecture.md` (arj).
- Trust calculator, EdgeScore selector and thresholds (isolation line, anomaly
  gate, rate-limit bands) ported into `turncoat_sdn.trust`, with
  `SimTrustModel` to plug the calculator into the simulator; the 0.44
  liar-floor tests, golden `zt_sdn` and `no_trust` numbers from the final-year
  project, `docs/concepts.md` and `docs/trust-model.md` (ash).
- Load-balancing strategies in `turncoat_sdn.strategies`
  (`RandomStrategy`, `RoundRobinStrategy`, `LeastConnectionsStrategy`,
  `NoTrustStrategy` and `ZeroTrustSDNStrategy`), with server validation,
  trust-threshold filtering, automated tests and `docs/strategies.md` (arv).

[Unreleased]: https://github.com/bhuvanesh-sudo/turncoat-sdn/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/bhuvanesh-sudo/turncoat-sdn/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/bhuvanesh-sudo/turncoat-sdn/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/bhuvanesh-sudo/turncoat-sdn/releases/tag/v0.1.0
