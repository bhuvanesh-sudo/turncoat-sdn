# Mininet backend (optional)

The live testbed lands in v1.0 (owner: bv). It will port `node_agent`,
`iot_client` and `topology` from the final-year project and write the same
`events.jsonl` schema as the simulator, so one set of scorers grades both.

This is the **only** place allowed to import os-ken, Ryu or Mininet. The core
package under `src/turncoat_sdn/` never depends on anything here, and is
installed and tested without it.
