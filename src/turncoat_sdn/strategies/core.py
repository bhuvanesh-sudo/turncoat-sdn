"""Core server models and load-balancing strategies."""

import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Server:
    """Represent an edge server and its current state."""

    server_id: str
    active_connections: int = 0
    healthy: bool = True
    trust_score: float = 1.0

    def __post_init__(self) -> None:
        if not self.server_id:
            raise ValueError("server_id must not be empty")
        if self.active_connections < 0:
            raise ValueError("Connections cannot be negative")
        if not 0 <= self.trust_score <= 1:
            raise ValueError("Trust must be between 0 and 1")


class Strategy(Protocol):
    """Interface that all load-balancing strategies must follow."""

    def select(self, servers: list[Server]) -> Server:
        """Choose a server for the next request."""
        ...


def eligible_servers(servers: list[Server]) -> list[Server]:
    """Return healthy servers or raise an error if none are available."""
    available = [server for server in servers if server.healthy]

    if not available:
        raise ValueError("No healthy servers available")

    return available


class RandomStrategy:
    """Select a random healthy server."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def select(self, servers: list[Server]) -> Server:
        return self.rng.choice(eligible_servers(servers))


class RoundRobinStrategy:
    """Select healthy servers in rotation."""

    def __init__(self) -> None:
        self.index = 0

    def select(self, servers: list[Server]) -> Server:
        available = eligible_servers(servers)
        server = available[self.index % len(available)]
        self.index = (self.index + 1) % len(available)
        return server


class LeastConnectionsStrategy:
    """Select the healthy server with the fewest active connections."""

    def select(self, servers: list[Server]) -> Server:
        return min(
            eligible_servers(servers),
            key=lambda server: server.active_connections,
        )


class NoTrustStrategy(LeastConnectionsStrategy):
    """Baseline that ignores trust scores and uses least connections."""


class ZeroTrustSDNStrategy:
    """Filter servers by health and trust, then prioritize trust."""

    def __init__(self, min_trust: float = 0.5) -> None:
        if not 0 <= min_trust <= 1:
            raise ValueError("Trust threshold must be between 0 and 1")
        self.min_trust = min_trust

    def select(self, servers: list[Server]) -> Server:
        candidates = [
            server for server in eligible_servers(servers) if server.trust_score >= self.min_trust
        ]

        if not candidates:
            raise ValueError("No healthy servers meet trust threshold")

        return min(
            candidates,
            key=lambda server: (
                -server.trust_score,
                server.active_connections,
            ),
        )
