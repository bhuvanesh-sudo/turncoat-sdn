import pytest

from turncoat_sdn.strategies import (
    LeastConnectionsStrategy,
    NoTrustStrategy,
    RandomStrategy,
    RoundRobinStrategy,
    Server,
    ZeroTrustSDNStrategy,
)


@pytest.fixture
def servers():
    return [
        Server("edge-a", 5, True, 0.9),
        Server("edge-b", 1, True, 0.8),
        Server("edge-c", 2, True, 0.3),
    ]


def test_round_robin(servers):
    strategy = RoundRobinStrategy()
    assert [strategy.select(servers).server_id for _ in range(3)] == ["edge-a", "edge-b", "edge-c"]


def test_least_connections(servers):
    assert LeastConnectionsStrategy().select(servers).server_id == "edge-b"


def test_no_trust_ignores_trust():
    servers = [
        Server("trusted", 5, True, 1.0),
        Server("untrusted", 0, True, 0.0),
    ]
    assert NoTrustStrategy().select(servers).server_id == "untrusted"


def test_zero_trust_prefers_highest_trust(servers):
    assert ZeroTrustSDNStrategy().select(servers).server_id == "edge-a"


def test_zero_trust_rejects_low_trust():
    servers = [Server("edge-a", trust_score=0.2)]
    with pytest.raises(ValueError, match="trust threshold"):
        ZeroTrustSDNStrategy(min_trust=0.5).select(servers)


def test_random_is_reproducible():
    servers = [Server(f"edge-{i}") for i in range(5)]
    a = RandomStrategy(seed=42)
    b = RandomStrategy(seed=42)
    assert [a.select(servers) for _ in range(20)] == [b.select(servers) for _ in range(20)]


def test_unhealthy_servers_are_skipped():
    servers = [
        Server("offline", healthy=False),
        Server("online", healthy=True),
    ]
    assert RoundRobinStrategy().select(servers).server_id == "online"


def test_no_healthy_servers():
    servers = [Server("offline", healthy=False)]
    for strategy in (
        RandomStrategy(seed=1),
        RoundRobinStrategy(),
        LeastConnectionsStrategy(),
        NoTrustStrategy(),
        ZeroTrustSDNStrategy(),
    ):
        with pytest.raises(ValueError, match="No healthy servers"):
            strategy.select(servers)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"server_id": ""},
        {"active_connections": -1},
        {"trust_score": -0.1},
        {"trust_score": 1.1},
    ],
)
def test_invalid_server_data(kwargs):
    with pytest.raises(ValueError):
        Server(**({"server_id": "edge-a"} | kwargs))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"server_id": " "},
        {"active_connections": True},
        {"active_connections": 1.5},
        {"trust_score": True},
        {"trust_score": float("nan")},
        {"trust_score": float("inf")},
        {"trust_score": float("-inf")},
    ],
)
def test_server_rejects_invalid_types_and_non_finite_values(kwargs):
    with pytest.raises(ValueError):
        Server(**({"server_id": "edge-a"} | kwargs))


@pytest.mark.parametrize(
    "threshold",
    [True, float("nan"), float("inf"), float("-inf")],
)
def test_zero_trust_rejects_invalid_threshold_values(threshold):
    with pytest.raises(ValueError, match="Trust threshold"):
        ZeroTrustSDNStrategy(min_trust=threshold)


def test_invalid_trust_threshold():
    with pytest.raises(ValueError, match="between 0 and 1"):
        ZeroTrustSDNStrategy(min_trust=1.5)


def test_empty_server_list():
    strategies = [
        RandomStrategy(seed=1),
        RoundRobinStrategy(),
        LeastConnectionsStrategy(),
        NoTrustStrategy(),
        ZeroTrustSDNStrategy(),
    ]

    for strategy in strategies:
        with pytest.raises(ValueError, match="No healthy servers"):
            strategy.select([])


def test_round_robin_handles_changing_server_list():
    strategy = RoundRobinStrategy()

    first = [
        Server("edge-a"),
        Server("edge-b"),
        Server("edge-c"),
    ]

    assert strategy.select(first).server_id == "edge-a"
    assert strategy.select(first).server_id == "edge-b"

    second = [Server("edge-c")]

    assert strategy.select(second).server_id == "edge-c"


def test_zero_trust_tie_breaks_by_connections():
    servers = [
        Server("edge-a", active_connections=5, trust_score=0.9),
        Server("edge-b", active_connections=2, trust_score=0.9),
    ]

    assert ZeroTrustSDNStrategy().select(servers).server_id == "edge-b"


def test_zero_trust_rejects_unhealthy_high_trust_server():
    servers = [
        Server("edge-a", healthy=False, trust_score=1.0),
        Server("edge-b", healthy=True, trust_score=0.8),
    ]

    assert ZeroTrustSDNStrategy().select(servers).server_id == "edge-b"
