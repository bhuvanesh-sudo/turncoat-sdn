"""The discrete-event loop: one seeded run, and paired runs over shared seeds.

Ported from the final-year project's ``evaluation/baseline.py``. The event loop
is unchanged; the selector, trust calculator and latency tell that it used to
import from the controller are now hooks (see :mod:`turncoat_sdn.sim.hooks`).

From v0.2 a run can also be recorded: pass a ``recorder`` and every routing
decision, task outcome and poll is written to it in the shared
``events.jsonl`` format. Recording draws no random numbers, so a recorded run
returns the same metrics as an unrecorded one.

From v0.3 attackers are :class:`turncoat_sdn.attacks.ServerAttack` objects
rather than branches in the loop. The loop asks each one how it serves a task
and what it reports at a poll, and the attack decides, honestly before its
``start_s`` and hostile after.

Also from v0.3, a run with a client attacker (a
:class:`turncoat_sdn.attacks.ClientAttack`) models the IoT devices: every
arrival comes from one of ``n_clients`` devices, and the controller's admission
check (:mod:`turncoat_sdn.sim.admission`) admits or refuses each request before
routing sees it. A run without one has no devices and no admission check, and
draws, routes and records exactly what it did before.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

from turncoat_sdn.attacks import ClientAttack, IdentitySpoof, ServerAttack, Status
from turncoat_sdn.sim.admission import BINDINGS, IdentityBinding, client_id, client_ip
from turncoat_sdn.sim.config import (
    ARRIVAL_SEED_OFFSET,
    ATTACK_SEED_OFFSET,
    CLIENT_ATTACK_SEED_OFFSET,
    CLIENT_SEED_OFFSET,
    JITTER_SEED_OFFSET,
    SCENARIOS,
    SELECTION_SEED_OFFSET,
    SERVICE_SEED_OFFSET,
    SimConfig,
    scenario_attacks,
    scenario_client_attacks,
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


def _topology(
    cfg: SimConfig,
    attackers: Mapping[int, ServerAttack],
    client_attackers: Mapping[int, ClientAttack],
) -> dict[str, Any]:
    """The roster and ground truth: each attacker's label and onset.

    IoT devices are listed only in a run that models them, one with a client
    attacker, so every other recording is unchanged.
    """
    nodes: list[dict[str, Any]] = []
    for i in range(cfg.n_nodes):
        node: dict[str, Any] = {"id": node_id(i), "kind": "server", "attack": "none"}
        if i in attackers:
            node.update(attackers[i].ground_truth())
        nodes.append(node)
    if client_attackers:
        for j in range(cfg.n_clients):
            device: dict[str, Any] = {
                "id": client_id(j),
                "kind": "iot",
                "ip": client_ip(j),
                "attack": "none",
            }
            if j in client_attackers:
                device.update(client_attackers[j].ground_truth())
            nodes.append(device)
    return {"nodes": nodes, "links": []}


def _check_attacks(attacks: Mapping[int, ServerAttack], n_nodes: int) -> dict[int, ServerAttack]:
    for i, attack in attacks.items():
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < n_nodes:
            raise ValueError(f"attack node index {i!r} is not in range(0, {n_nodes})")
        if not isinstance(attack, ServerAttack):
            raise TypeError(f"attack at node {i} must be a ServerAttack, got {attack!r}")
    return dict(attacks)


def _check_client_attacks(
    attacks: Mapping[int, ClientAttack], n_clients: int
) -> dict[int, ClientAttack]:
    for j, attack in attacks.items():
        if isinstance(j, bool) or not isinstance(j, int) or not 0 <= j < n_clients:
            raise ValueError(f"client attack index {j!r} is not in range(0, {n_clients})")
        if not isinstance(attack, ClientAttack):
            raise TypeError(f"attack at client {j} must be a ClientAttack, got {attack!r}")
        if isinstance(attack, IdentitySpoof):
            if not attack.target < n_clients:
                raise ValueError(f"spoof target {attack.target} is not in range(0, {n_clients})")
            if attack.target == j:
                raise ValueError(f"client {j} cannot spoof its own identity")
    return dict(attacks)


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
    attacks: Mapping[int, ServerAttack] | None = None,
    client_attacks: Mapping[int, ClientAttack] | None = None,
) -> RunResult:
    """Run one seeded simulation and return its metrics.

    Args:
        router: Builds the routing strategy for this run.
        scenario: One of :data:`~turncoat_sdn.sim.config.SCENARIOS`. Places
            the run's attackers unless ``attacks`` is given; it is also the
            run's label.
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
        attacks: The attackers, by node index, in place of the scenario's.
            Each is a :class:`turncoat_sdn.attacks.ServerAttack` with its own
            onset. ``{}`` runs with no server attacker.
        client_attacks: The client attackers, by client index (0 is
            ``iot1``), in place of the scenario's. Each is a
            :class:`turncoat_sdn.attacks.ClientAttack`. Any client attacker
            turns on the IoT devices and the admission check for the run.
            ``{}`` runs with no client attacker.

    The same seed hands every strategy an identical workload. Each kind of draw
    has its own :class:`random.Random`, so the k-th arrival carries the same
    service demand however the strategies diverge (common random numbers).
    That pairing is what licenses a signed-rank test across strategies.
    """
    cfg = config or SimConfig()
    n = cfg.n_nodes
    if attacks is None:
        attackers = scenario_attacks(scenario, cfg)
    else:
        attackers = _check_attacks(attacks, n)
    if cfg.identity_binding not in BINDINGS:
        raise ValueError(
            f"identity_binding must be one of {BINDINGS}, got {cfg.identity_binding!r}"
        )
    client_attackers = _check_client_attacks(
        scenario_client_attacks(scenario, cfg) if client_attacks is None else client_attacks,
        cfg.n_clients,
    )
    clients_on = bool(client_attackers)

    arr_rng = random.Random(seed + ARRIVAL_SEED_OFFSET)  # interarrival times
    svc_rng = random.Random(seed + SERVICE_SEED_OFFSET)  # service demands
    jit_rng = random.Random(seed + JITTER_SEED_OFFSET)  # /status RTT jitter
    sel_rng = random.Random(seed + SELECTION_SEED_OFFSET)  # routing decisions
    # One stream per attacker, for attacks that draw (a grayhole's drops).
    atk_rng = {i: random.Random(seed + ATTACK_SEED_OFFSET + i) for i in attackers}
    # Only a run with IoT clients draws these, from streams of their own.
    cli_rng = random.Random(seed + CLIENT_SEED_OFFSET)  # which device sends each arrival
    catk_rng = {j: random.Random(seed + CLIENT_ATTACK_SEED_OFFSET + j) for j in client_attackers}
    binding = IdentityBinding(
        cfg.identity_binding,
        roster={client_id(j): client_ip(j) for j in range(cfg.n_clients)},
    )
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
        rec.write(
            "topology", 0.0, graph=_topology(cfg, attackers, client_attackers), config=asdict(cfg)
        )

    def is_excluded(i: int) -> bool:
        """Whether the isolation threshold or the anomaly gate holds node ``i`` out."""
        return trust_scores[i] < cfg.isolation_threshold or anomaly[i] >= cfg.anomaly_gate

    def begin_service(i: int, task: _Task, now: float) -> None:
        """Occupy a worker on node ``i`` with ``task``."""
        busy[i] += 1
        demand = task[1]
        attack = attackers.get(i)
        if attack is not None:
            service = attack.service_time(now, demand, atk_rng[i])
        else:
            service = demand
        if service is None:
            # Accepts the task, holds the worker, and never finishes it.
            heapq.heappush(evq, (now + cfg.task_timeout_s, next(counter), "timeout", i, task))
        else:
            heapq.heappush(evq, (now + service, next(counter), "dep", i, task))

    def dispatch(now: float, demand: float, source_ip: str | None) -> None:
        """Offer an admitted task to the router, then serve or queue it."""
        result.offered += 1
        task_id = result.offered
        i = chooser.choose(trust_scores, claimed_cpu, rtt_ms, anomaly)
        sender = {"client_ip": source_ip} if source_ip is not None else {}

        if i is None:
            # Every node quarantined: deny by default. It counts against
            # the strategy, so isolating the whole fleet is never free.
            result.failed += 1
            result.slo_violations += 1
            if rec is not None:
                rec.write("route_denied", _ts(now), reason=DENIED_REASON, task=task_id, **sender)
            return

        result.served[i] += 1
        if i in attackers and attackers[i].active(now):
            result.malicious_tasks += 1
        if rec is not None:
            rec.write("route", _ts(now), task=task_id, chosen=node_id(i), **sender)

        arriving = (now, demand, task_id)
        if busy[i] < cfg.concurrency:
            begin_service(i, arriving, now)
        else:
            backlog[i].append(arriving)

    def refuse(now: float, device: str, source_ip: str, denial: str) -> None:
        """Record a request the admission check turned away before routing."""
        if rec is not None:
            rec.write("auth_denied", _ts(now), device_id=device, source_ip=source_ip, kind=denial)

    heapq.heappush(evq, (arr_rng.expovariate(lam), next(counter), "arr", -1, None))
    heapq.heappush(evq, (cfg.poll_s, next(counter), "poll", -1, None))
    for j, client_attack in client_attackers.items():
        heapq.heappush(evq, (client_attack.first_request_s(), next(counter), "cli", j, None))

    while evq:
        now, _, kind, node, task = heapq.heappop(evq)
        if now > cfg.sim_s:
            break

        if kind == "poll":
            # What each node reports, and how fast it answers.
            for i in range(n):
                jitter = jit_rng.uniform(-cfg.rtt_jitter_ms, cfg.rtt_jitter_ms)
                inflight = busy[i] + len(backlog[i])
                reported = Status(min(1.0, inflight / cfg.concurrency), cfg.base_rtt_ms + jitter)
                attack = attackers.get(i)
                if attack is not None:
                    reported = attack.status(now, reported, jitter, atk_rng[i])
                claimed_cpu[i], rtt_ms[i] = reported

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
            # A turncoat only counts once it has turned: excluding it before its
            # onset is not catching it.
            if attackers and result.time_to_isolate_s is None:
                if all(a.active(now) and is_excluded(i) for i, a in attackers.items()):
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
            # Drawn here, from its own stream, so the k-th arrival carries the
            # same service demand whichever strategy routes it.
            demand = svc_rng.expovariate(1 / cfg.service_mean_s)
            # Choosing a node schedules nothing, so pushing the next arrival
            # before it keeps every event's tiebreak counter what it was.
            heapq.heappush(evq, (now + arr_rng.expovariate(lam), next(counter), "arr", -1, None))
            source = None
            if clients_on:
                # Every arrival is some device's ordinary traffic, sent as itself.
                sender_j = cli_rng.randrange(cfg.n_clients)
                device, source = client_id(sender_j), client_ip(sender_j)
                denial = binding.admit(device, source)
                if denial is not None:
                    # Only under tofu, once a spoofer owns this device's identity.
                    result.honest_refused += 1
                    refuse(now, device, source, denial)
                    continue
            dispatch(now, demand, source)
            continue

        if kind == "cli":
            # A request a client attacker sends of its own, from its own address.
            attacker = client_attackers[node]
            claimed = attacker.identity(node, now)
            if isinstance(claimed, bool) or not isinstance(claimed, int):
                raise TypeError(f"{attacker!r} claimed {claimed!r}, not a client index")
            if not 0 <= claimed < cfg.n_clients:
                raise ValueError(f"{attacker!r} claimed client {claimed}, not in the fleet")
            source = client_ip(node)
            result.client_attack_requests += 1
            denial = binding.admit(client_id(claimed), source)
            if denial is not None:
                result.client_attack_refused += 1
                refuse(now, client_id(claimed), source, denial)
            else:
                dispatch(now, catk_rng[node].expovariate(1 / cfg.service_mean_s), source)
            following = attacker.next_request_s(now, catk_rng[node])
            if following is not None:
                heapq.heappush(evq, (following, next(counter), "cli", node, None))
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
