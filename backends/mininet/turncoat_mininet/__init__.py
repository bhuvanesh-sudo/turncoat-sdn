"""turncoat-sdn's optional live backend: the benchmark on a real network under Mininet.

Owner: bv (Simulator track).
Lands in: v1.0.
Ported from the final-year project:
simulation/node_agent.py, simulation/topology.py, simulation/addressing.py and
the client half of simulation/iot_client.py.

Modules:

* :mod:`~turncoat_mininet.node_agent`: the agent on each edge server, driven by
  a :class:`turncoat_sdn.attacks.ServerAttack`;
* :mod:`~turncoat_mininet.iot_client`: a device sending tasks;
* :mod:`~turncoat_mininet.controller`: routing, trust, detection and the
  ``events.jsonl`` recording, all from the core package;
* :mod:`~turncoat_mininet.topology`: the seeded plan, the Mininet build and the
  launch commands;
* :mod:`~turncoat_mininet.run`: one run, on Mininet or on loopback.

This is the only place in the repository allowed to import Mininet (and only
:func:`~turncoat_mininet.topology.build_network` and its helpers do). The core
package never imports anything here.
"""

__all__ = ["addressing", "controller", "iot_client", "node_agent", "run", "topology"]
