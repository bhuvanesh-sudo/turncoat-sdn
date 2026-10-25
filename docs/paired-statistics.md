**# Paired Benchmark Statistics**

**Owner:** arv · **Written in:** v0.4

**## What it is**

The paired benchmark statistics module compares two load-balancing strategies using repeated runs performed with matching scenario and seed values. It provides a paired Wilcoxon signed-rank test, mean and median paired differences, pair counts, and Holm-Bonferroni correction for multiple p-values.

**## Why it exists**

Different random seeds can produce different workload outcomes. Comparing strategies using matching seeds helps control variation caused by the simulation workload. The Wilcoxon signed-rank test evaluates whether paired differences provide evidence against the specified null hypothesis. Holm correction controls the family-wise error rate when conducting multiple hypothesis tests.

**## How to use it**

```python
from turncoat_sdn.stats.paired import paired_wilcoxon, holm_adjust

records = [
    {"strategy": "random", "scenario": "sybil", "seed": 1, "slo_violation_rate": 0.20},
    {"strategy": "random", "scenario": "sybil", "seed": 2, "slo_violation_rate": 0.25},
    {"strategy": "zero_trust", "scenario": "sybil", "seed": 1, "slo_violation_rate": 0.10},
    {"strategy": "zero_trust", "scenario": "sybil", "seed": 2, "slo_violation_rate": 0.15},
]

result = paired_wilcoxon(
    records,
    strategy_a="random",
    strategy_b="zero_trust",
    scenario="sybil",
    metric="slo_violation_rate",
)

print(result.mean_difference)
print(result.p_value)

adjusted = holm_adjust([0.01, 0.04, 0.03])
print(adjusted)
```

Run the checks from the repository root:

```bash
pytest tests/stats/test_paired.py
pytest
ruff check .
ruff format --check .
```

**## How it works inside**

**### Paired Wilcoxon signed-rank test**

`paired_wilcoxon(rows, strategy_a, strategy_b, scenario, metric)` matches records by seed within the requested scenario. It calculates differences as `strategy_a - strategy_b` and applies SciPy's Wilcoxon signed-rank test.

The result contains the strategy names, scenario, metric, number of complete pairs, number of pairs excluded because of missing metric values, test statistic, raw p-value, mean difference, median difference, and alternative hypothesis.

The `alternative` argument accepts `two-sided`, `less`, or `greater`. The default is `two-sided`.

**### Holm-Bonferroni correction**

`holm_adjust(p_values)` returns adjusted p-values in the same order as the supplied values. It sorts p-values, applies the step-down Holm procedure, enforces monotonic adjusted values in sorted order, and caps results at 1.

For multiple comparisons, collect the raw p-values from the planned tests and pass them together to `holm_adjust`. Do not interpret each raw p-value as if it were already corrected.

**### Input validation**

Strategy names, scenario, and metric must be non-empty strings. Strategies must differ. Each selected strategy must have exactly one row for each matching seed; duplicate rows and mismatched seed sets are rejected.

Seeds must be integers. Metric values must be finite numeric values or missing (`None` or an empty string). If either strategy's metric is missing for a seed, that pair is excluded. If no complete pairs remain, the comparison raises an error.

If all paired differences are zero, the implementation returns a statistic of zero and a p-value of one. Invalid p-values passed to `holm_adjust` are rejected.

**## Integration status**

This module is implemented in `src/turncoat_sdn/stats/paired.py`. Its automated tests are in `tests/stats/test_paired.py`.

It uses the existing SciPy dependency. It does not execute simulations, change strategy behavior, or replace scoring functions. The CLI `turncoat compare` command and automated comparison-report integration are separate follow-up work.

**## Known limits**

- Comparisons require matching scenario and seed values; unmatched runs are rejected rather than silently discarded.
- Missing metric values exclude the entire affected pair.
- The Wilcoxon test assumes a suitable paired experimental design; matching seeds alone does not guarantee that every statistical assumption is satisfied.
- Very small samples can provide limited statistical power.
- Mean and median differences describe the observed effect but are not confidence intervals.
- The reported p-value is unadjusted until it is passed through `holm_adjust` with the other tests in the same correction family.
- The module does not currently generate a complete strategy-comparison report or provide the `turncoat compare` CLI command.
