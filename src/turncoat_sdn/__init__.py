"""turncoat-sdn: a benchmark for trust-aware SDN load balancers under turncoat attacks.

A *turncoat* is a node that behaves honestly at first, earns trust, and then
turns hostile after its onset time (``start_s``). This package will provide a
seeded simulator, a library of delayed-onset attacks, one shared event format
(``events.jsonl``), and scorers plus paired statistics that grade any run.

Subpackages
-----------
sim
    Seeded discrete-event simulator of edge servers and IoT clients.
attacks
    One module per turncoat attack profile.
strategies
    Load-balancing strategies behind one ``Strategy`` interface.
trust
    Trust calculator, edge selector and thresholds.
events
    Event schema, JSONL writer and reader, validator.
scoring
    Attack, NFR, interval and availability scorers.
stats
    Paired Wilcoxon with Holm correction, bootstrap CIs, aggregator.

The core package never imports os-ken, Ryu or Mininet; those belong to the
optional live backend under ``backends/``.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("turncoat-sdn")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
