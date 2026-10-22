"""EMA-based trust calculator for edge nodes.

Trust formula::

    T(t) = alpha*R(t) + beta*B(t) + gamma*H(t) - delta*A(t)

where each component is an exponential moving average of its raw value::

    X(t) = lambda*x(t) + (1 - lambda)*X(t-1)

Ported unchanged from the final-year project's
``trust_engine/trust_calculator.py``, with the ``TrustUpdate`` record from
``contracts/trust_update.py`` beside it. :class:`SimTrustModel` is new: it fits
the calculator to the simulator's trust hook, the way the project's
``evaluation/baseline.py`` called it.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

TaskStatus = Literal["success", "failure", "timeout"]

#: Task status -> raw reputation value.
_STATUS_MAP: dict[str, float] = {
    "success": 1.0,
    "failure": 0.0,
    "timeout": 0.3,
}


@dataclass
class TrustUpdate:
    """One task outcome and the telemetry that came with it."""

    device_id: str
    edge_node_id: str
    timestamp: float = field(default_factory=time.time)
    task_status: TaskStatus = "success"
    cpu_usage: float = 0.0
    """Actual CPU load, 0 to 1."""
    reported_cpu: float = 0.0
    """What the node claimed its load was, 0 to 1."""
    latency_ms: float = 0.0
    """Raw observed latency."""
    trust_score_before: float = 0.5
    trust_score_after: float = 0.5
    anomaly_flag: bool = False

    def honesty_delta(self) -> float:
        """Deviation between reported and actual CPU. Feeds the H component."""
        return abs(self.reported_cpu - self.cpu_usage)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class TrustCalculator:
    """Calculates and tracks per-node trust scores using EMA-smoothed components.

    Attributes:
        alpha: Reputation weight (R, task success).
        beta: Behavioural consistency weight (B, latency).
        gamma: Resource honesty weight (H, claimed vs actual CPU).
        delta: Attack suspicion weight (A, anomaly flag).
        lambda_decay: EMA decay factor.
        initial_score: Starting trust for unseen nodes.
    """

    def __init__(
        self,
        alpha: float = 0.35,
        beta: float = 0.25,
        gamma: float = 0.25,
        delta: float = 0.15,
        lambda_decay: float = 0.85,
        initial_score: float = 0.5,
    ) -> None:
        """Initialise the TrustCalculator.

        Raises:
            AssertionError: If alpha + beta + gamma + delta != 1.0
        """
        weight_sum = round(alpha + beta + gamma + delta, 10)
        assert weight_sum == 1.0, (
            f"Trust weights must sum to 1.0, got {weight_sum} "
            f"(a={alpha}, b={beta}, g={gamma}, d={delta})"
        )

        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta
        self.lambda_decay = lambda_decay
        self.initial_score = initial_score

        # Per-node EMA state: {node_id: {'R': float, 'B': float, 'H': float, 'A': float}}
        self._ema: dict[str, dict[str, float]] = {}
        # Per-node final trust score cache
        self._scores: dict[str, float] = {}

        logger.info(
            "TrustCalculator initialised: a=%.2f b=%.2f g=%.2f d=%.2f lam=%.2f",
            alpha,
            beta,
            gamma,
            delta,
            lambda_decay,
        )

    def _init_node(self, node_id: str) -> None:
        """Initialise EMA state for a previously-unseen node."""
        self._ema[node_id] = {
            "R": self.initial_score,
            "B": self.initial_score,
            "H": self.initial_score,
            "A": 0.0,
        }
        self._scores[node_id] = self.initial_score

    def update(self, upd: TrustUpdate) -> float:
        """Process a TrustUpdate and return the new trust score.

        Updates the EMA state for the edge node identified in the update,
        computes the new composite trust score, and clips it to [0.0, 1.0].

        Args:
            upd: A TrustUpdate record with task outcome and telemetry. Its
                ``trust_score_before`` and ``trust_score_after`` are filled in.

        Returns:
            The updated trust score in [0.0, 1.0].
        """
        node_id = upd.edge_node_id

        if node_id not in self._ema:
            self._init_node(node_id)

        ema = self._ema[node_id]
        lam = self.lambda_decay

        # --- Raw component values ---
        r_raw = _STATUS_MAP.get(upd.task_status, 0.3)
        b_raw = max(0.0, 1.0 - upd.latency_ms / 500.0)
        h_raw = max(0.0, 1.0 - upd.honesty_delta() / 0.5)
        a_raw = 1.0 if upd.anomaly_flag else 0.0

        # --- EMA smoothing ---
        ema["R"] = lam * r_raw + (1 - lam) * ema["R"]
        ema["B"] = lam * b_raw + (1 - lam) * ema["B"]
        ema["H"] = lam * h_raw + (1 - lam) * ema["H"]
        ema["A"] = lam * a_raw + (1 - lam) * ema["A"]

        # --- Composite trust score ---
        score = (
            self.alpha * ema["R"]
            + self.beta * ema["B"]
            + self.gamma * ema["H"]
            - self.delta * ema["A"]
        )
        score = max(0.0, min(1.0, score))

        # Store and annotate the update
        upd.trust_score_before = self._scores.get(node_id, self.initial_score)
        self._scores[node_id] = score
        upd.trust_score_after = score

        logger.debug(
            "Trust update: node=%s status=%s score=%.4f->%.4f (R=%.3f B=%.3f H=%.3f A=%.3f)",
            node_id,
            upd.task_status,
            upd.trust_score_before,
            score,
            ema["R"],
            ema["B"],
            ema["H"],
            ema["A"],
        )

        return score

    def get_score(self, node_id: str) -> float:
        """Return the current trust score for a node, or initial_score if unseen."""
        return self._scores.get(node_id, self.initial_score)

    def get_all_scores(self) -> dict[str, float]:
        """Return a copy of all tracked node trust scores."""
        return dict(self._scores)

    def get_components(self, node_id: str) -> dict[str, float]:
        """Return a copy of a node's smoothed R, B, H and A, or the starting values if unseen."""
        if node_id not in self._ema:
            return {
                "R": self.initial_score,
                "B": self.initial_score,
                "H": self.initial_score,
                "A": 0.0,
            }
        return dict(self._ema[node_id])


class TaskOutcome(Protocol):
    """The fields :class:`SimTrustModel` reads from a finished task.

    :class:`turncoat_sdn.sim.Outcome` has all of them. It is described here
    rather than imported, so ``trust`` does not depend on ``sim``.
    """

    @property
    def edge_node_id(self) -> str: ...

    @property
    def timestamp(self) -> float: ...

    @property
    def task_status(self) -> TaskStatus: ...

    @property
    def cpu_usage(self) -> float: ...

    @property
    def reported_cpu(self) -> float: ...

    @property
    def latency_ms(self) -> float: ...

    @property
    def anomaly_flag(self) -> bool: ...


class SimTrustModel:
    """The trust calculator in the shape of the simulator's ``TrustModel`` hook.

    Pass the class itself as the hook. The simulator calls it with no
    arguments once per run, so every run starts from fresh EMA state::

        from turncoat_sdn.sim import simulate
        from turncoat_sdn.trust import SimTrustModel, latency_tell

        run = simulate(router, "sybil", seed=1, trust=SimTrustModel, latency_tell=latency_tell)

    Each outcome becomes a ``TrustUpdate`` exactly as the project's
    ``evaluation/baseline.py`` built it, with ``device_id="sim"``.
    """

    def __init__(self, calculator: TrustCalculator | None = None) -> None:
        self.calculator = calculator if calculator is not None else TrustCalculator()

    @property
    def initial_score(self) -> float:
        return self.calculator.initial_score

    def update(self, outcome: TaskOutcome) -> float:
        return self.calculator.update(
            TrustUpdate(
                device_id="sim",
                edge_node_id=outcome.edge_node_id,
                timestamp=outcome.timestamp,
                task_status=outcome.task_status,
                cpu_usage=outcome.cpu_usage,
                reported_cpu=outcome.reported_cpu,
                latency_ms=outcome.latency_ms,
                anomaly_flag=outcome.anomaly_flag,
            )
        )
