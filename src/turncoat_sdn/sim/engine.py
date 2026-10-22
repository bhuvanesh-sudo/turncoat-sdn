"""The discrete-event loop: one seeded run, and paired runs over shared seeds.

Ported from the final-year project's ``evaluation/baseline.py``. The event loop
is unchanged; the selector, trust calculator and latency tell that it used to
import from the controller are now hooks (see :mod:`turncoat_sdn.sim.hooks`).
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import deque
from collections.abc import Iterable, Mapping, Sequence

from turncoat_sdn.sim.config import (
    ARRIVAL_SEED_OFFSET,
    JITTER_SEED_OFFSET,
    SCENARIOS,
    SELECTION_SEED_OFFSET,
    SERVICE_SEED_OFFSET,
    SimConfig,
    malicious_roles,
)
from turncoat_sdn.sim.hooks import LatencyTell, Outcome, RouterFactory, TrustModelFactory
from turncoat_sdn.sim.result import RunResult

#: Trust every node holds for the whole run when no trust model is given.
UNTRUSTED_DEFAULT = 1.0

# A queued task is (arrived_at, service_demand_s).
_Task = tuple[float, float]


def _strategy_name(router: RouterFactory) -> str:
    return getattr(router, "name", None) or getattr(router, "__name__", type(router).__name__)


def simulate(
    router: RouterFactory,
    scenario: str,
    seed: int,
    *,
    config: SimConfig | None = None,
    trust: TrustModelFactory | None = None,
    latency_tell: LatencyTell | None = None,
    name: str | None = None,
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
                if latency_tell is not None:
                    tell = latency_tell.evaluate_latency_tell(
                        claimed_cpu=claimed_cpu[i],
                        measured_rtt_ms=rtt_ms[i],
                        fleet_baseline_ms=baseline,
                        strikes=strikes[i],
                    )
                    strikes[i] = tell.strikes
                    raw = 1.0 if tell.tripped else 0.0

                history = recent_statuses[i]
                if len(history) >= cfg.min_timeout_samples:
                    timeout_rate = sum(1 for s in history if s == "timeout") / len(history)
                    if timeout_rate > cfg.honesty_deviation_threshold:
                        raw = 1.0

                anomaly[i] = cfg.anomaly_ema * raw + (1 - cfg.anomaly_ema) * anomaly[i]

            # First moment every attacker is excluded from routing.
            if roles and result.time_to_isolate_s is None:
                if all(
                    trust_scores[i] < cfg.isolation_threshold or anomaly[i] >= cfg.anomaly_gate
                    for i in roles
                ):
                    result.time_to_isolate_s = now

            heapq.heappush(evq, (now + cfg.poll_s, next(counter), "poll", -1, None))
            continue

        if kind == "arr":
            result.offered += 1
            # Drawn here, from its own stream, so the k-th arrival carries the
            # same service demand whichever strategy routes it.
            demand = svc_rng.expovariate(1 / cfg.service_mean_s)
            i = chooser.choose(trust_scores, claimed_cpu, rtt_ms, anomaly)
            heapq.heappush(evq, (now + arr_rng.expovariate(lam), next(counter), "arr", -1, None))

            if i is None:
                # Every node quarantined: deny by default. It counts against
                # the strategy, so isolating the whole fleet is never free.
                result.failed += 1
                result.slo_violations += 1
                continue

            result.served[i] += 1
            if i in roles:
                result.malicious_tasks += 1

            arriving = (now, demand)
            if busy[i] < cfg.concurrency:
                begin_service(i, arriving, now)
            else:
                backlog[i].append(arriving)
            continue

        # Completion or timeout: update trust exactly as the live controller does.
        assert task is not None
        busy[node] -= 1
        arrived, _ = task
        latency_ms = (now - arrived) * 1000.0
        timed_out = kind == "timeout"

        if timed_out:
            result.failed += 1
            result.slo_violations += 1
        else:
            result.completed += 1
            result.latencies_ms.append(latency_ms)
            if latency_ms > cfg.slo_ms:
                result.slo_violations += 1

        # Free worker: pull the next task off this node's backlog. Anything that
        # waited longer than the client timeout has already given up.
        while backlog[node] and busy[node] < cfg.concurrency:
            queued = backlog[node].popleft()
            if now - queued[0] >= cfg.task_timeout_s:
                result.failed += 1
                result.slo_violations += 1
                continue
            begin_service(node, queued, now)

        status = "timeout" if timed_out else "success"
        recent_statuses[node].append(status)
        if model is not None:
            actual_cpu = min(1.0, (busy[node] + len(backlog[node])) / cfg.concurrency)
            trust_scores[node] = model.update(
                Outcome(
                    node=node,
                    edge_node_id=f"srv{node + 1}",
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
) -> list[RunResult]:
    """Run every strategy against every scenario on the same seeds.

    Seeds are shared across strategies on purpose: run ``k`` of every strategy
    faces the identical workload and attacker, which is what makes the samples
    paired. Results come back ordered by scenario, then seed, then strategy.
    """
    seed_list = list(seeds)
    results: list[RunResult] = []
    for scenario in scenarios:
        for seed in seed_list:
            for label, router in strategies.items():
                results.append(
                    simulate(
                        router,
                        scenario,
                        seed,
                        config=config,
                        trust=trust,
                        latency_tell=latency_tell,
                        name=label,
                    )
                )
    return results
