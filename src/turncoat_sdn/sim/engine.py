"""The discrete-event loop: one seeded run, and paired runs over shared seeds.

Ported from the final-year project's ``evaluation/baseline.py``. The event loop
is unchanged; the selector, trust calculator and latency tell that it used to
import from the controller are now hooks (see :mod:`turncoat_sdn.sim.hooks`).

From v0.2 a run can also be recorded: pass a ``recorder`` and every routing
decision, task outcome and poll is written to it in the shared
``events.jsonl`` format. Recording draws no random numbers, so a recorded run
returns the same metrics as an unrecorded one.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

from turncoat_sdn.sim.config import (
    ARRIVAL_SEED_OFFSET,
    JITTER_SEED_OFFSET,
    SCENARIOS,
    SELECTION_SEED_OFFSET,
    SERVICE_SEED_OFFSET,
    SimConfig,
    malicious_roles,
)
from turncoat_sdn.sim.hooks import (
    LatencyTell,
    Outcome,
    Recorder,
    RecorderFactory,
    RouterFactory,
    TrustModelFactory,
)
from turncoat_sdn.sim.result import RunResult

#: Trust every node holds for the whole run when no trust model is given.
UNTRUSTED_DEFAULT = 1.0

#: Signal names on recorded ``anomaly`` events. They match the attack
#: classifier's ``SIG_LATENCY_TELL`` and ``SIG_PACKET_DROP``; ``sim`` cannot
#: import ``scoring``, so a test keeps the two in step.
SIGNAL_LATENCY_TELL = "latency_tell"
SIGNAL_PACKET_DROP = "packet_drop"

#: ``reason`` on a recorded ``route_denied``: the router refused the task.
DENIED_REASON = "all candidates quarantined"

# A queued task is (arrived_at, service_demand_s, task_id).
_Task = tuple[float, float, int]


def _strategy_name(router: RouterFactory) -> str:
    return getattr(router, "name", None) or getattr(router, "__name__", type(router).__name__)


def node_id(i: int) -> str:
    """The id node ``i`` goes by in recordings and trust outcomes: ``srv1`` for 0."""
    return f"srv{i + 1}"


def _ts(t: float) -> float:
    # Rounding is monotone, so rounded timestamps stay in time order.
    return round(t, 6)


def _topology(cfg: SimConfig, roles: Mapping[int, str]) -> dict[str, Any]:
    """The roster and ground truth: every attacker is hostile from the start."""
    nodes: list[dict[str, Any]] = []
    for i in range(cfg.n_nodes):
        node: dict[str, Any] = {"id": node_id(i), "kind": "server", "attack": roles.get(i, "none")}
        if i in roles:
            node["attack_start_s"] = 0.0
        nodes.append(node)
    return {"nodes": nodes, "links": []}


def simulate(
    router: RouterFactory,
    scenario: str,
    seed: int,
    *,
    config: SimConfig | None = None,
    trust: TrustModelFactory | None = None,
    latency_tell: LatencyTell | None = None,
    name: str | None = None,
    recorder: Recorder | None = None,
) -> RunResult:
    """Run one seeded simulation and return its metrics.

    Args:
        router: Builds the routing strategy for this run.
        scenario: One of :data:`~turncoat_sdn.sim.config.SCENARIOS`.
        seed: Fixes the arrival stream, service demands, RTT jitter and the
            router's random stream.
        config: Fleet, workload and attacker settings. Defaults to
            :class:`SimConfig` as shipped.
        trust: Builds the trust model. Without one, every node keeps trust
            :data:`UNTRUSTED_DEFAULT` all run.
        latency_tell: The Sybil tell. Without one, only the timeout-rate tell
            raises a node's anomaly level.
        name: Strategy label for the result. Defaults to the router's ``name``
            attribute or ``__name__``.
        recorder: Receives the run as ``events.jsonl`` events, starting with
            the ``topology``. Pass an open
            :class:`turncoat_sdn.events.EventWriter`, which has already
            written the ``header``. The caller closes it.

    The same seed hands every strategy an identical workload. Each kind of draw
    has its own :class:`random.Random`, so the k-th arrival carries the same
    service demand however the strategies diverge (common random numbers).
    That pairing is what licenses a signed-rank test across strategies.
    """
    cfg = config or SimConfig()
    n = cfg.n_nodes
    roles = malicious_roles(scenario, n)

    arr_rng = random.Random(seed + ARRIVAL_SEED_OFFSET)  # interarrival times
    svc_rng = random.Random(seed + SERVICE_SEED_OFFSET)  # service demands
    jit_rng = random.Random(seed + JITTER_SEED_OFFSET)  # /status RTT jitter
    sel_rng = random.Random(seed + SELECTION_SEED_OFFSET)  # routing decisions
    chooser = router(n, sel_rng)
    model = trust() if trust is not None else None

    lam = cfg.arrival_rate

    # Each node is an M/M/c queue: `concurrency` workers, then a FIFO backlog.
    # Without the backlog a task's latency would just be its own service draw,
    # routing could not affect it, and every strategy would score the same
    # whenever no attacker was present.
    busy = [0] * n
    backlog: list[deque[_Task]] = [deque() for _ in range(n)]
    claimed_cpu = [0.0] * n
    rtt_ms = [cfg.base_rtt_ms] * n
    anomaly = [0.0] * n
    strikes = [0] * n
    trust_scores = [model.initial_score if model is not None else UNTRUSTED_DEFAULT] * n
    recent_statuses: list[deque[str]] = [deque(maxlen=cfg.recent_status_window) for _ in range(n)]

    result = RunResult(
        strategy=name or _strategy_name(router),
        scenario=scenario,
        seed=seed,
        served=[0] * n,
    )

    # (time, tiebreak, kind, node, task). The counter keeps the ordering total
    # and deterministic when two events land on the same timestamp.
    evq: list[tuple[float, int, str, int, _Task | None]] = []
    counter = itertools.count()

    rec = recorder
    # Which nodes the exclusion rails held out at the last poll, so a recording
    # writes ``quarantine`` and ``recovered`` on the edges only.
    excluded = [False] * n
    if rec is not None:
        rec.write("topology", 0.0, graph=_topology(cfg, roles), config=asdict(cfg))

    def is_excluded(i: int) -> bool:
        """Whether the isolation threshold or the anomaly gate holds node ``i`` out."""
        return trust_scores[i] < cfg.isolation_threshold or anomaly[i] >= cfg.anomaly_gate

    def begin_service(i: int, task: _Task, now: float) -> None:
        """Occupy a worker on node ``i`` with ``task``."""
        busy[i] += 1
        if roles.get(i) == "drop":
            # Accepts the task, holds the worker, and never finishes it.
            heapq.heappush(evq, (now + cfg.task_timeout_s, next(counter), "timeout", i, task))
        else:
            demand = task[1]
            if roles.get(i) == "sybil":
                demand *= cfg.sybil_slowdown
            heapq.heappush(evq, (now + demand, next(counter), "dep", i, task))

    heapq.heappush(evq, (arr_rng.expovariate(lam), next(counter), "arr", -1, None))
    heapq.heappush(evq, (cfg.poll_s, next(counter), "poll", -1, None))

    while evq:
        now, _, kind, node, task = heapq.heappop(evq)
        if now > cfg.sim_s:
            break

        if kind == "poll":
            # What each node reports, and how fast it answers.
            for i in range(n):
                jitter = jit_rng.uniform(-cfg.rtt_jitter_ms, cfg.rtt_jitter_ms)
                if roles.get(i) == "sybil":
                    claimed_cpu[i] = cfg.sybil_claimed_cpu
                    rtt_ms[i] = cfg.sybil_rtt_ms + jitter
                else:
                    inflight = busy[i] + len(backlog[i])
                    claimed_cpu[i] = min(1.0, inflight / cfg.concurrency)
                    rtt_ms[i] = cfg.base_rtt_ms + jitter

            # The controller's anomaly detection: two independent tells that
            # catch different attackers. The latency tell catches the Sybil
            # (claims idle, answers slowly); the timeout-rate tell catches the
            # dropper (its tasks never come back).
            baseline = (
                latency_tell.fleet_latency_baseline(rtt_ms) if latency_tell is not None else None
            )
            for i in range(n):
                raw = 0.0
                # What fired, for the recording: signal name to strength.
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

                if rec is not None and signals:
                    rec.write(
                        "anomaly",
                        _ts(now),
                        node=node_id(i),
                        signals=signals,
                        anomaly=round(anomaly[i], 6),
                    )

            # First moment every attacker is excluded from routing.
            if roles and result.time_to_isolate_s is None:
                if all(is_excluded(i) for i in roles):
                    result.time_to_isolate_s = now

            if rec is not None:
                for i in range(n):
                    out = is_excluded(i)
                    if out != excluded[i]:
                        excluded[i] = out
                        rec.write(
                            "quarantine" if out else "recovered",
                            _ts(now),
                            node=node_id(i),
                            trust=round(trust_scores[i], 6),
                            anomaly=round(anomaly[i], 6),
                        )
                # Closes the poll cycle: the attack scorer reads every node
                # without an ``anomaly`` since the last one as clean.
                rec.write(
                    "node_status",
                    _ts(now),
                    nodes={
                        node_id(i): {
                            "trust": round(trust_scores[i], 6),
                            "claimed_cpu": round(claimed_cpu[i], 6),
                            "rtt_ms": round(rtt_ms[i], 3),
                            "anomaly": round(anomaly[i], 6),
                            "busy": busy[i],
                            "queued": len(backlog[i]),
                        }
                        for i in range(n)
                    },
                )

            heapq.heappush(evq, (now + cfg.poll_s, next(counter), "poll", -1, None))
            continue

        if kind == "arr":
            result.offered += 1
            # Drawn here, from its own stream, so the k-th arrival carries the
            # same service demand whichever strategy routes it.
            demand = svc_rng.expovariate(1 / cfg.service_mean_s)
            i = chooser.choose(trust_scores, claimed_cpu, rtt_ms, anomaly)
            heapq.heappush(evq, (now + arr_rng.expovariate(lam), next(counter), "arr", -1, None))
            task_id = result.offered

            if i is None:
                # Every node quarantined: deny by default. It counts against
                # the strategy, so isolating the whole fleet is never free.
                result.failed += 1
                result.slo_violations += 1
                if rec is not None:
                    rec.write("route_denied", _ts(now), reason=DENIED_REASON, task=task_id)
                continue

            result.served[i] += 1
            if i in roles:
                result.malicious_tasks += 1
            if rec is not None:
                rec.write("route", _ts(now), task=task_id, chosen=node_id(i))

            arriving = (now, demand, task_id)
            if busy[i] < cfg.concurrency:
                begin_service(i, arriving, now)
            else:
                backlog[i].append(arriving)
            continue

        # Completion or timeout: update trust exactly as the live controller does.
        assert task is not None
        busy[node] -= 1
        arrived, _, task_id = task
        latency_ms = (now - arrived) * 1000.0
        timed_out = kind == "timeout"
        status = "timeout" if timed_out else "success"

        if timed_out:
            result.failed += 1
            result.slo_violations += 1
        else:
            result.completed += 1
            result.latencies_ms.append(latency_ms)
            if latency_ms > cfg.slo_ms:
                result.slo_violations += 1
        if rec is not None:
            rec.write(
                "report",
                _ts(now),
                task=task_id,
                node=node_id(node),
                status=status,
                latency_ms=round(latency_ms, 3),
            )

        # Free worker: pull the next task off this node's backlog. Anything that
        # waited longer than the client timeout has already given up.
        while backlog[node] and busy[node] < cfg.concurrency:
            queued = backlog[node].popleft()
            if now - queued[0] >= cfg.task_timeout_s:
                result.failed += 1
                result.slo_violations += 1
                if rec is not None:
                    # The client gave up at the timeout; the simulator only
                    # notices now, when a worker reaches the task.
                    rec.write(
                        "report",
                        _ts(now),
                        task=queued[2],
                        node=node_id(node),
                        status="timeout",
                        latency_ms=cfg.task_timeout_s * 1000.0,
                        gave_up_in_backlog=True,
                    )
                continue
            begin_service(node, queued, now)

        recent_statuses[node].append(status)
        if model is not None:
            actual_cpu = min(1.0, (busy[node] + len(backlog[node])) / cfg.concurrency)
            trust_scores[node] = model.update(
                Outcome(
                    node=node,
                    edge_node_id=node_id(node),
                    timestamp=now,
                    task_status=status,
                    cpu_usage=actual_cpu,
                    reported_cpu=claimed_cpu[node],
                    latency_ms=latency_ms,
                    anomaly_flag=anomaly[node] >= cfg.anomaly_gate,
                )
            )

    return result


def run_paired(
    strategies: Mapping[str, RouterFactory],
    seeds: Iterable[int],
    scenarios: Sequence[str] = SCENARIOS,
    *,
    config: SimConfig | None = None,
    trust: TrustModelFactory | None = None,
    latency_tell: LatencyTell | None = None,
    recorders: RecorderFactory | None = None,
) -> list[RunResult]:
    """Run every strategy against every scenario on the same seeds.

    Seeds are shared across strategies on purpose: run ``k`` of every strategy
    faces the identical workload and attacker, which is what makes the samples
    paired. Results come back ordered by scenario, then seed, then strategy.

    ``recorders`` opens a recorder for each run, given its strategy label,
    scenario and seed. Each one is closed after its run if it has a ``close``
    method, so a factory returning :class:`turncoat_sdn.events.EventWriter`
    leaves one finished file per run.
    """
    seed_list = list(seeds)
    results: list[RunResult] = []
    for scenario in scenarios:
        for seed in seed_list:
            for label, router in strategies.items():
                rec = recorders(label, scenario, seed) if recorders is not None else None
                try:
                    results.append(
                        simulate(
                            router,
                            scenario,
                            seed,
                            config=config,
                            trust=trust,
                            latency_tell=latency_tell,
                            name=label,
                            recorder=rec,
                        )
                    )
                finally:
                    close = getattr(rec, "close", None)
                    if close is not None:
                        close()
    return results
