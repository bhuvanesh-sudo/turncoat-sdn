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
