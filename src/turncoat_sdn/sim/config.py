"""Simulator settings and the built-in scenarios.

Every default mirrors the module constants of the final-year project's
``evaluation/baseline.py``, which in turn mirror ``config/params_trust_demo.yaml``
and the live controller. Change them through :class:`SimConfig`, never by
editing the defaults: the golden-file tests pin the numbers they produce.
"""

from __future__ import annotations

from dataclasses import dataclass

from turncoat_sdn.attacks import (
    Blackhole,
    ClientAttack,
    Grayhole,
    IdentitySpoof,
    OnOff,
    ServerAttack,
    Sybil,
)

#: The built-in attack scenarios, in reporting order. ``grayhole``, ``onoff``
#: and ``spoof`` arrived in v0.3, after the final-year project's four, so they
#: report last.
SCENARIOS: tuple[str, ...] = ("clean", "sybil", "drop", "both", "grayhole", "onoff", "spoof")

# Offsets that give each random stream its own seed. Changing any of them
# changes every simulated number, so they are part of the golden contract.
ARRIVAL_SEED_OFFSET = 0
SERVICE_SEED_OFFSET = 17
JITTER_SEED_OFFSET = 43
SELECTION_SEED_OFFSET = 99
#: Attacker at node index ``i`` draws from ``seed + ATTACK_SEED_OFFSET + i``.
#: Its own stream, so an attack that draws random numbers never shifts the
#: workload the strategies are paired on.
ATTACK_SEED_OFFSET = 211
#: Which client sends each arrival, in a run with IoT clients. Its own stream,
#: so attributing arrivals to clients moves nothing else.
CLIENT_SEED_OFFSET = 157
#: Client attacker ``j`` draws from ``seed + CLIENT_ATTACK_SEED_OFFSET + j``,
#: clear of the server attackers' streams for fleets of up to 96 servers.
CLIENT_ATTACK_SEED_OFFSET = 307


@dataclass(frozen=True)
class SimConfig:
    """Everything that shapes one run except the seed, scenario and strategy.

    Build a variant with :func:`dataclasses.replace`, for example
    ``replace(SimConfig(), n_nodes=4, sim_s=60.0)``.
    """

    # --- Fleet and workload ------------------------------------------------
    n_nodes: int = 8
    """Edge servers. The deck's full scale; 4 hits the capacity cliff in ``both``."""
    concurrency: int = 4
    """Workers per node. Each node is an M/M/c queue with a FIFO backlog."""
    service_mean_s: float = 0.20
    """Mean honest service time (exponential)."""
    load_factor: float = 0.4
    """Offered load as a fraction of total farm capacity.

    0.4 keeps the farm stable in the worst scenario: with 2 of 4 nodes
    quarantined, the honest half carries 0.4 * 4 / 2 = 80% utilisation.
    """
    sim_s: float = 120.0
    """Simulated seconds per run."""

    # --- Controller view ---------------------------------------------------
    poll_s: float = 1.0
    """How often the controller refreshes claimed load and RTT."""
    base_rtt_ms: float = 50.0
    """Healthy ``/status`` round-trip."""
    rtt_jitter_ms: float = 4.0
    """Uniform jitter added to every measured RTT, in both directions."""
    anomaly_ema: float = 0.85
    """Weight of the newest raw anomaly flag in the smoothed anomaly level."""

    # Timeout-rate tell, mirroring TrustState.recent_timeout_rate: the fraction
    # of a node's last ``recent_status_window`` outcomes that timed out, flagged
    # above ``honesty_deviation_threshold`` once ``min_timeout_samples`` exist.
    recent_status_window: int = 10
    min_timeout_samples: int = 4
    honesty_deviation_threshold: float = 0.40

    # Exclusion rails used to timestamp ``time_to_isolate_s`` and to set the
    # anomaly flag passed to the trust model. The canonical values belong to
    # turncoat_sdn.trust; these copies keep the simulator usable on its own.
    isolation_threshold: float = 0.3
    anomaly_gate: float = 0.5

    # --- Clients -----------------------------------------------------------
    task_timeout_s: float = 2.0
    """How long a client waits before giving up on a task."""
    slo_ms: float = 500.0
    """Completion deadline that defines an SLO violation."""

    # --- Attackers ---------------------------------------------------------
    sybil_claimed_cpu: float = 0.1
    """What the Sybil reports as its load, whatever the truth."""
    sybil_slowdown: float = 2.0
    """Service-time multiplier for the Sybil.

    It must stay below 2.5, where the Sybil can no longer absorb its fair share,
    saturates, and starts timing tasks out. Past that it becomes a failing node
    that trust isolates on its own, which is a much easier attack.
    """
    sybil_rtt_ms: float = 220.0
    """How slowly the Sybil answers ``/status``. This is the latency tell."""
    grayhole_drop_fraction: float = 0.5
    """Share of the tasks it accepts that the grayhole drops once it turns.

    The observed timeout rate runs higher, about 0.6, because a dropped task
    holds its worker until the client gives up and the backlog behind it waits.
    Much past 0.7 the classifier starts calling it a blackhole.
    """
    onoff_on_s: float = 10.0
    """Length of each hostile phase of the on-off attacker, which lies like the Sybil."""
    onoff_off_s: float = 10.0
    """Length of each honest phase between them.

    Keep it at 3 s or more: the classifier needs a few clean polls to see the
    attacker go quiet, and a shorter honest phase is labelled ``sybil``.
    """
    attack_start_s: float = 0.0
    """Onset of the scenario's built-in attackers, in simulated seconds.

    Before it they behave honestly; 0.0 makes them hostile from the start, as
    in the final-year project. It does not apply to attackers passed to
    :func:`~turncoat_sdn.sim.simulate` as ``attacks`` or ``client_attacks``,
    which carry their own.
    """

    # --- IoT clients and admission (only in a run with a client attacker) --
    n_clients: int = 40
    """IoT devices sending the work, ``iot1`` to ``iot40`` as in the project.

    A run with no client attacker has no clients: one anonymous arrival stream
    and no admission check, exactly as before v0.3.
    """
    identity_binding: str = "roster"
    """How the controller binds device ids to addresses: ``roster`` or ``tofu``.

    ``roster`` is the project's fix after live run 9; ``tofu`` gives an
    unclaimed identity to whoever claims it first. See
    :mod:`turncoat_sdn.sim.admission`.
    """
    spoof_attacker: int = 37
    """Client index of the scenario's spoofer: ``iot38``, as in the project."""
    spoof_target: int = 0
    """Client index of the device it impersonates: ``iot1``, as in the project."""
    spoof_interval_s: float = 2.0
    """Seconds between the spoofer's requests as its target."""

    @property
    def capacity(self) -> float:
        """Tasks per second the whole farm can serve when every node is honest."""
        return self.n_nodes * self.concurrency / self.service_mean_s

    @property
    def arrival_rate(self) -> float:
        """Offered tasks per second (Poisson)."""
        return self.load_factor * self.capacity


def scenario_attacks(scenario: str, config: SimConfig | None = None) -> dict[int, ServerAttack]:
    """Return the attackers ``scenario`` places, keyed by node index.

    Attackers sit at the end of the index range so they are never the node a
    round-robin happens to start on. Every one turns at
    ``config.attack_start_s``.
    """
    cfg = config or SimConfig()
    n = cfg.n_nodes

    def sybil() -> Sybil:
        return Sybil(
            cfg.attack_start_s,
            claimed_cpu=cfg.sybil_claimed_cpu,
            slowdown=cfg.sybil_slowdown,
            rtt_ms=cfg.sybil_rtt_ms,
        )

    if scenario in ("clean", "spoof"):
        return {}
    if scenario == "sybil":
        return {n - 1: sybil()}
    if scenario == "drop":
        return {n - 1: Blackhole(cfg.attack_start_s)}
    if scenario == "both":
        return {n - 1: sybil(), n - 2: Blackhole(cfg.attack_start_s)}
    if scenario == "grayhole":
        return {n - 1: Grayhole(cfg.attack_start_s, drop_fraction=cfg.grayhole_drop_fraction)}
    if scenario == "onoff":
        return {
            n - 1: OnOff(
                cfg.attack_start_s,
                on_s=cfg.onoff_on_s,
                off_s=cfg.onoff_off_s,
                claimed_cpu=cfg.sybil_claimed_cpu,
                slowdown=cfg.sybil_slowdown,
                rtt_ms=cfg.sybil_rtt_ms,
            )
        }
    raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")


def scenario_client_attacks(
    scenario: str, config: SimConfig | None = None
) -> dict[int, ClientAttack]:
    """Return the client attackers ``scenario`` places, keyed by client index.

    Only ``spoof`` has one so far. It turns at ``config.attack_start_s``.
    """
    cfg = config or SimConfig()
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    if scenario == "spoof":
        return {
            cfg.spoof_attacker: IdentitySpoof(
                cfg.attack_start_s, target=cfg.spoof_target, interval_s=cfg.spoof_interval_s
            )
        }
    return {}


def malicious_roles(scenario: str, n_nodes: int) -> dict[int, str]:
    """Return which node indices misbehave in ``scenario``, and their attack labels."""
    attacks = scenario_attacks(scenario, SimConfig(n_nodes=n_nodes))
    return {i: attack.name for i, attack in attacks.items()}
