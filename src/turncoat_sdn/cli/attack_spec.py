"""``--attack``: add an attacker to a ``turncoat run`` from the command line.

A spec is the attack's name, then optional ``key=value`` settings, separated
by commas::

    spoof
    spoof,client=iot38,target=iot5,start=15
    sybil,node=srv3,start=30
    grayhole,start=20

Each spec adds one attacker to the scenario's own. The attack's behaviour
comes from the run's :class:`~turncoat_sdn.sim.SimConfig`, exactly as the
built-in scenario of the same name would build it; the spec only says who
attacks, whom, and when.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from turncoat_sdn.attacks import ClientAttack, ServerAttack
from turncoat_sdn.sim import SimConfig, scenario_attacks, scenario_client_attacks

#: Attack name -> the built-in scenario that builds it. ``blackhole`` is the
#: standard name for the attack recorded as ``drop``; both are accepted.
SERVER_ATTACKS: dict[str, str] = {
    "sybil": "sybil",
    "blackhole": "drop",
    "drop": "drop",
    "grayhole": "grayhole",
    "onoff": "onoff",
}
CLIENT_ATTACKS: dict[str, str] = {"spoof": "spoof"}
#: Every name ``--attack`` takes, in the order ``--help`` lists them.
ATTACK_NAMES: tuple[str, ...] = ("sybil", "blackhole", "grayhole", "onoff", "spoof")

_KEYS = {
    **{name: ("node", "start") for name in SERVER_ATTACKS},
    "spoof": ("client", "target", "start"),
}
_SERVER = re.compile(r"srv([1-9][0-9]*)")
_CLIENT = re.compile(r"iot([1-9][0-9]*)")


class AttackSpecError(ValueError):
    """A ``--attack`` spec that cannot be parsed or placed."""


@dataclass(frozen=True)
class AttackSpec:
    """One parsed ``--attack``. Indices are 0-based: ``srv1`` and ``iot1`` are 0."""

    name: str
    node: int | None = None
    client: int | None = None
    target: int | None = None
    start: float | None = None


def _index(value: str, pattern: re.Pattern[str], key: str, example: str) -> int:
    match = pattern.fullmatch(value)
    if match is None:
        raise AttackSpecError(f"{key}={value!r} is not a device name like {example}")
    return int(match.group(1)) - 1


def parse_attack(text: str) -> AttackSpec:
    """Parse one ``--attack`` value."""
    name, *settings = [part.strip() for part in text.split(",")]
    if name not in _KEYS:
        raise AttackSpecError(f"unknown attack {name!r}; expected one of {', '.join(ATTACK_NAMES)}")
    allowed = _KEYS[name]
    values: dict[str, int | float] = {}
    for setting in settings:
        key, sep, value = setting.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise AttackSpecError(f"{setting!r} in {text!r} is not key=value")
        if key not in allowed:
            raise AttackSpecError(f"{name} takes {', '.join(allowed)}; {key!r} is not one of them")
        if key in values:
            raise AttackSpecError(f"{key} is given twice in {text!r}")
        if key == "node":
            values[key] = _index(value, _SERVER, key, "srv3")
        elif key in ("client", "target"):
            values[key] = _index(value, _CLIENT, key, "iot38")
        else:
            try:
                start = float(value)
            except ValueError:
                raise AttackSpecError(f"start={value!r} is not a number of seconds") from None
            if not (math.isfinite(start) and start >= 0):
                raise AttackSpecError(f"start={value!r} must be 0 or more seconds")
            values[key] = start
    return AttackSpec(name=name, **values)  # type: ignore[arg-type]


def place_attacks(
    specs: list[AttackSpec], scenario: str, config: SimConfig
) -> tuple[dict[int, ServerAttack], dict[int, ClientAttack]]:
    """The scenario's attackers plus one per spec, as the simulator takes them.

    A spec with no ``node`` takes the highest-numbered server nobody attacks
    from yet. A spoof with no ``client`` is the configured spoofer (``iot38``)
    if it is free, and impersonates the configured target (``iot1``). A spec
    with no ``start`` turns at the run's onset, ``config.attack_start_s``.
    """
    attacks = scenario_attacks(scenario, config)
    client_attacks = scenario_client_attacks(scenario, config)

    for spec in specs:
        start = config.attack_start_s if spec.start is None else spec.start
        cfg = replace(config, attack_start_s=start)

        if spec.name in SERVER_ATTACKS:
            if spec.node is None:
                free = [i for i in range(cfg.n_nodes) if i not in attacks]
                if not free:
                    raise AttackSpecError(f"no server is free for {spec.name}")
                node = free[-1]
            else:
                node = spec.node
            if not node < cfg.n_nodes:
                raise AttackSpecError(f"srv{node + 1} is not in a fleet of {cfg.n_nodes} servers")
            if node in attacks:
                raise AttackSpecError(f"srv{node + 1} already runs {attacks[node].name}")
            # The scenario of the same name builds it at the last server; take it from there.
            built = scenario_attacks(SERVER_ATTACKS[spec.name], cfg)
            attacks[node] = built[cfg.n_nodes - 1]
            continue

        target = cfg.spoof_target if spec.target is None else spec.target
        if spec.client is not None:
            client = spec.client
        elif cfg.spoof_attacker not in client_attacks and cfg.spoof_attacker != target:
            client = cfg.spoof_attacker
        else:
            free = [j for j in range(cfg.n_clients) if j not in client_attacks and j != target]
            if not free:
                raise AttackSpecError("no IoT device is free to spoof from")
            client = free[-1]
        for who, j in (("client", client), ("target", target)):
            if not j < cfg.n_clients:
                raise AttackSpecError(f"{who} iot{j + 1} is not in a fleet of {cfg.n_clients}")
        if client == target:
            raise AttackSpecError(f"iot{client + 1} cannot spoof its own identity")
        if client in client_attacks:
            raise AttackSpecError(f"iot{client + 1} already runs {client_attacks[client].name}")
        placed = replace(cfg, spoof_attacker=client, spoof_target=target)
        client_attacks.update(scenario_client_attacks(CLIENT_ATTACKS[spec.name], placed))

    return attacks, client_attacks
