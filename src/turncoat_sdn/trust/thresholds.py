"""Decision thresholds for excluding a node: the isolation line and the anomaly gate.

Ported from the final-year project's ``contracts/thresholds.py``. These are the
canonical values. :class:`turncoat_sdn.sim.SimConfig` keeps its own copies so
the simulator stays usable on its own, and ``tests/trust`` checks the copies
still match.

The project's file also held the controller's quarantine-escape constants
(evidence age, probation interval, busy-time span) and the client task
timeout. Those belong to the live controller's ``TrustState`` and the IoT
client, not to the trust model, so they were not moved.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

#: Trust score below which a node is excluded from routing.
DEFAULT_ISOLATION_THRESHOLD = 0.3

#: Smoothed anomaly level at or above which a node is quarantined regardless of
#: its trust score.
#:
#: This gate is not part of the published trust formula. It is necessary
#: because the formula cannot isolate a node that lies about its load but still
#: serves tasks well: such a node holds R -> 1 and B -> 0.96, so
#:
#:     T = 0.35(1.0) + 0.25(0.96) + 0.25(0.0) - 0.15(1.0) = 0.44
#:
#: which never crosses :data:`DEFAULT_ISOLATION_THRESHOLD`, because delta only
#: ever subtracts 0.15. Dishonesty alone can drive H to 0 and A to 1 and still
#: leave the node comfortably above the isolation line. Continuous verification
#: therefore needs an anomaly gate alongside the score.
DEFAULT_ANOMALY_GATE = 0.5

# --- Graduated response bands ----------------------------------------------
#
# Zero Trust is not binary trust/no-trust: a node that is merely *suspect* --
# below full trust but not yet over the quarantine line -- gets a proportional
# response rather than either full service or none. In the live controller a
# node in the middle band still receives traffic, but its flows are
# rate-limited by an OpenFlow meter.
#
#   trust >= RATE_LIMIT_TRUST  and  anomaly < ANOMALY_WARN   -> full service
#   ISOLATION <= trust < RATE_LIMIT_TRUST, or                -> rate-limited
#       ANOMALY_WARN <= anomaly < ANOMALY_GATE
#   trust < ISOLATION  or  anomaly >= ANOMALY_GATE           -> quarantined
#
# The gates (ISOLATION, ANOMALY_GATE) stay as the hard safety rails; these two
# thresholds only carve the "suspect" band out of the region above them.

#: Trust below which a node that is not quarantined is rate-limited.
DEFAULT_RATE_LIMIT_TRUST = 0.5

#: Smoothed anomaly level at or above which a node that is not quarantined is
#: rate-limited.
DEFAULT_ANOMALY_WARN = 0.25
