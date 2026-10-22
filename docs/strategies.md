# Strategies

**Owner:** arv · **Written in:** v0.1

## What it is

The load-balancing strategies available in `turncoat_sdn.strategies`: random, round robin, least connections, no trust and Zero Trust SDN. Each strategy implements the same `Strategy` interface, so the simulator or another caller can choose a routing policy without depending on a particular implementation.

## Why it exists

The final-year project evaluates different load-balancing policies under normal and adversarial conditions. These policies need a common interface so they can be compared using the same simulator, attack scenarios and recorded outcomes.

The no-trust baseline deliberately ignores trust scores, while the Zero Trust strategy filters servers by health and a minimum trust threshold. Keeping the policies in a pure Python package allows the core to run without os-ken, Ryu or Mininet.

## How to use it

Import the server model and the strategy you want to evaluate:

```python
from turncoat_sdn.strategies import (
    LeastConnectionsStrategy,
    Server,
    ZeroTrustSDNStrategy,
)

servers = [
    Server("edge-a", active_connections=5, trust_score=0.9),
    Server("edge-b", active_connections=2, trust_score=0.8),
]

baseline = LeastConnectionsStrategy()
zero_trust = ZeroTrustSDNStrategy(min_trust=0.5)

print(baseline.select(servers).server_id)
print(zero_trust.select(servers).server_id)
```

Each strategy receives a list of `Server` objects and returns the selected server. Unhealthy servers are excluded. If no healthy server is available, selection raises `ValueError`. The Zero Trust strategy also raises `ValueError` if no healthy server meets its trust threshold.

Run the project checks from the repository root:

```bash
pytest
ruff check .
ruff format --check .
```

## How it works inside

### Server model

`Server` is an immutable dataclass with four fields:

| Field | Meaning |
|---|---|
| `server_id` | Non-empty identifier for the edge server |
| `active_connections` | Number of active connections; cannot be negative |
| `healthy` | Whether the server is eligible for selection |
| `trust_score` | Trust score between `0.0` and `1.0` |

### Available strategies

| Strategy | Selection rule |
|---|---|
| `RandomStrategy` | Selects a random healthy server. Accepts an optional seed for reproducible selection. |
| `RoundRobinStrategy` | Cycles through the healthy servers in list order. |
| `LeastConnectionsStrategy` | Selects the healthy server with the fewest active connections. |
| `NoTrustStrategy` | Uses least connections without considering trust scores. |
| `ZeroTrustSDNStrategy` | Excludes unhealthy servers and servers below the configured trust threshold; prioritizes higher trust scores and uses fewer active connections to break ties. |

The default trust threshold is `0.5`. The threshold can be changed when creating `ZeroTrustSDNStrategy`.

**Design note:** The highest-trust-first rule describes the current implementation. Confirm it against the team's agreed trust model before treating it as the final Zero Trust policy.

### Interface and dependency boundaries

`Strategy` is a Python `Protocol` with a `select(servers)` method. Each concrete strategy follows this interface.

The strategy package contains pure Python logic. It must not import os-ken, Ryu or Mininet. The caller is responsible for supplying the current server state and using the selected server.

### How the rules are tested

`tests/test_strategies.py` checks:

- Round-robin ordering and behaviour when the server list changes.
- Least-connections selection and the no-trust baseline.
- Trust-threshold filtering and selection tie-breaking.
- Reproducible random selection with an explicit seed.
- Exclusion of unhealthy servers and errors when no eligible server exists.
- Validation of server data and trust thresholds.

Run `pytest` to execute the full test suite, not only the strategy-specific tests.

## Known limits

- The strategy classes have been tested independently; integration with the simulator must be verified separately.
- `ZeroTrustSDNStrategy` currently uses the highest-trust-first selection rule. The team must confirm that this matches the intended design and trust model.
- The `Server` model contains a snapshot of connection count, health and trust. The caller must update these values as the simulation progresses.
- The current tests validate the implemented behaviour, not whether the selection policy is the best policy for every attack scenario.
