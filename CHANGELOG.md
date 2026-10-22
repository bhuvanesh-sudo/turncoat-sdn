# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every pull request adds one line under **Unreleased**, in the section that
fits (Added, Changed, Fixed, Removed).

## [Unreleased]

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
- Attack scoring in `turncoat_sdn.scoring`: the attack classifier and attack
  report moved from the final-year project, printing a confusion matrix,
  per-class metrics and detection latency for a recording; tests including a
  scored simulator run, and the attack scoring section of `docs/scoring.md`
  (ash).