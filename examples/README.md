# Examples

Runnable examples land in v1.0:

- **Quick scenario:** one seeded run, scored end to end.
- **Custom strategy** (arv): a new load-balancing strategy, plus scoring a
  recording from an outside system.
- **Custom attack** (ash): [`custom_attack.py`](custom_attack.py), a new
  turncoat in under 50 lines of code. The *slowpoke* serves every task four
  times slower but never lies; the example runs it on paired seeds, scores
  every run, and finds that it costs SLO violations without ever being
  quarantined. Run `python examples/custom_attack.py`; the walk-through is in
  [docs/extending.md](../docs/extending.md#your-own-attack).

Every example runs in CI, so none of them can silently go stale.
