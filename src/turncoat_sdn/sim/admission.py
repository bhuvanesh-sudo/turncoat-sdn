"""The controller's admission check: which address may speak for which device.

Ported from the final-year project's ``security/authenticator.py``
(``IdentityBinding``), without the cipher. The project's PRESENT-80 key was
fleet-wide, so any device holding it produced a correct response for *any*
device id. Cryptography therefore never told a spoofer apart from the device
it impersonated, and the simulator does not model it: every enrolled device
passes it. What decides is this binding of each device id to a source address.

Two rules, as in the project:

``roster``
    The binding is provisioned: device ``iot<N>`` may only speak from its own
    address, whether or not it has spoken yet. A claim from any other address
    is refused. The project's default after live run 9.

``tofu``
    Trust on first use: the first address to claim a device id is pinned to it,
    and later claims from other addresses are refused. Whoever gets there first
    owns the identity. In live run 9 the real iot1's first handshake failed,
    the identity sat unclaimed, and iot38 took it; the project then moved to
    the roster. Kept here because it is still the right default for a fleet you
    do not know in advance, and because the benchmark should be able to show
    what it costs.

A refusal carries the project's denial tag, ``ip_pin``: a correct key from the
wrong host. The attack classifier names that ``spoof``.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Accepted values of :attr:`SimConfig.identity_binding`.
BINDINGS: tuple[str, ...] = ("roster", "tofu")

#: Denial tag for a claim from the wrong address. The live authenticator's
#: ``AUTH_DENY_IP_PIN``, and the ``kind`` the attack scorer reads as spoofing.
DENY_IP_PIN = "ip_pin"


def client_id(j: int) -> str:
    """The id client ``j`` goes by in recordings: ``iot1`` for 0."""
    return f"iot{j + 1}"


def client_ip(j: int) -> str:
    """Client ``j``'s address, as the project assigned it: ``10.0.0.1`` for 0."""
    return f"10.0.0.{j + 1}"


class IdentityBinding:
    """Which address may claim which device id, under one of :data:`BINDINGS`.

    Holds per-run state, so the simulator builds a fresh one for every run.

    Args:
        rule: ``roster`` or ``tofu``.
        roster: Device id to provisioned address. Required for ``roster``,
            ignored for ``tofu``.
    """

    def __init__(self, rule: str, roster: Mapping[str, str] | None = None) -> None:
        if rule not in BINDINGS:
            raise ValueError(f"identity binding must be one of {BINDINGS}, got {rule!r}")
        self.rule = rule
        self._provisioned = dict(roster or {}) if rule == "roster" else {}
        self._pinned: dict[str, str] = {}

    def admit(self, device_id: str, source_ip: str) -> str | None:
        """Check a claim of ``device_id`` from ``source_ip``.

        Returns ``None`` when the claim is admitted, or the denial tag when it
        is refused. An admitted ``tofu`` claim pins the identity to its address
        if nobody has claimed it yet.
        """
        if self.rule == "roster":
            owner = self._provisioned.get(device_id)
            if owner is not None:
                return None if owner == source_ip else DENY_IP_PIN
            # An identity nobody provisioned falls back to first use, as live.
        owner = self._pinned.get(device_id)
        if owner is None:
            self._pinned[device_id] = source_ip
            return None
        return None if owner == source_ip else DENY_IP_PIN

    def owner(self, device_id: str) -> str | None:
        """The address entitled to ``device_id`` right now, if any."""
        return self._provisioned.get(device_id) or self._pinned.get(device_id)
