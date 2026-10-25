# Examples

Three runnable examples, one for each way to plug your own work into the
benchmark. Run them from the repository root after `pip install -e .`. Each
prints a real result in under a minute, and each has a test in
`tests/examples/` that runs it as a script, so CI catches one that goes
stale. The walk-through for all three is in
[docs/extending.md](../docs/extending.md).

| Example | What it shows | Run it |
|---|---|---|
| [`custom_attack.py`](custom_attack.py) | A new turncoat in under 50 lines of code. The *slowpoke* serves every task four times slower but never lies; over paired seeds it costs SLO violations under every strategy and is never quarantined. | `python examples/custom_attack.py` |
| [`custom_strategy.py`](custom_strategy.py) | A new load-balancing strategy in under 50 lines of code. *Gated round robin* is round robin that skips servers the trust floor or anomaly gate holds out; over paired seeds of `both` it has fewer SLO violations than `zt_sdn` and far fewer failures than round robin. | `python examples/custom_strategy.py` |
| [`score_outside_recording.py`](score_outside_recording.py) | Grading a system that is not ours. A toy controller that imports nothing from turncoat-sdn writes `events.jsonl` with the standard library; turncoat-sdn validates it and names its blackhole, exactly as for a simulated run. | `python examples/score_outside_recording.py` |

`custom_attack.py` and `custom_strategy.py` take `--seeds N` for a quicker
run and `--record PATH` to write one run for `turncoat score`;
`score_outside_recording.py` takes `-o PATH`.
