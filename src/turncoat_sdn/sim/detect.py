"""The controller's anomaly detection at one poll, shared by every backend.

Moved out of the simulator's event loop in v1.0 so the live Mininet backend
(``backends/mininet/``) runs the very same decision on real ``/status`` polls
and real task outcomes. The arithmetic and its order are unchanged, so the
golden files still pin it.

Two independent tells catch different attackers. The latency tell catches the
Sybil (claims idle, answers slowly); the timeout-rate tell catches the dropper
(its tasks never come back). Either one raises the node's smoothed anomaly
level, and the exclusion rails read that level and the trust score.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from turncoat_sdn.sim.hooks import LatencyTell

#: Signal names on recorded ``anomaly`` events. They match the attack
#: classifier's ``SIG_LATENCY_TELL`` and ``SIG_PACKET_DROP``; ``sim`` cannot
#: import ``scoring``, so a test keeps the two in step.
SIGNAL_LATENCY_TELL = "latency_tell"
SIGNAL_PACKET_DROP = "packet_drop"


class DetectionSettings(Protocol):
    """The settings detection reads. :class:`~turncoat_sdn.sim.SimConfig` has them all."""

    @property
    def anomaly_ema(self) -> float: ...

    @property
    def min_timeout_samples(self) -> int: ...

    @property
    def honesty_deviation_threshold(self) -> float: ...

    @property
    def isolation_threshold(self) -> float: ...

    @property
    def anomaly_gate(self) -> float: ...


def detect_anomalies(
    claimed_cpu: Sequence[float],
    rtt_ms: Sequence[float],
    recent_statuses: Sequence[Sequence[str]],
    anomaly: list[float],
    strikes: list[int],
    cfg: DetectionSettings,
    latency_tell: LatencyTell | None,
) -> list[dict[str, float]]:
    """Run one poll's detection over every node, in node order.

    Args:
        claimed_cpu: What each node reported as its load at this poll.
        rtt_ms: How long each node took to answer this poll.
        recent_statuses: Each node's latest task outcomes, ``"success"`` or
            ``"timeout"``, oldest first, already cut to the window.
        anomaly: Each node's smoothed anomaly level. Updated in place.
        strikes: Each node's latency-tell strike count. Updated in place.
        cfg: The detection settings.
        latency_tell: The Sybil tell, or ``None`` to rely on timeouts alone.

    Returns:
        For each node, what fired this poll: signal name to strength. An empty
        dict means a clean observation, and no ``anomaly`` event is recorded.
    """
    baseline = latency_tell.fleet_latency_baseline(rtt_ms) if latency_tell is not None else None
    fired: list[dict[str, float]] = []
    for i in range(len(anomaly)):
        raw = 0.0
        signals: dict[str, float] = {}
        if latency_tell is not None:
            tell = latency_tell.evaluate_latency_tell(
                claimed_cpu=claimed_cpu[i],
                measured_rtt_ms=rtt_ms[i],
                fleet_baseline_ms=baseline,
                strikes=strikes[i],
            )
            strikes[i] = tell.strikes
            raw = 1.0 if tell.tripped else 0.0
            if tell.tripped:
                ratio = getattr(tell, "ratio", None)
                if ratio is None:
                    ratio = rtt_ms[i] / baseline if baseline else 1.0
                signals[SIGNAL_LATENCY_TELL] = ratio

        history = recent_statuses[i]
        if len(history) >= cfg.min_timeout_samples:
            timeout_rate = sum(1 for s in history if s == "timeout") / len(history)
            if timeout_rate > cfg.honesty_deviation_threshold:
                raw = 1.0
                signals[SIGNAL_PACKET_DROP] = timeout_rate

        anomaly[i] = cfg.anomaly_ema * raw + (1 - cfg.anomaly_ema) * anomaly[i]
        fired.append(signals)
    return fired


def is_excluded(trust: float, anomaly: float, cfg: DetectionSettings) -> bool:
    """Whether the isolation threshold or the anomaly gate holds a node out."""
    return trust < cfg.isolation_threshold or anomaly >= cfg.anomaly_gate
