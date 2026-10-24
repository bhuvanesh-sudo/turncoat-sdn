# Benchmark Statistics

**Owner:** arv · **Written in:** v0.3

## What it is

The benchmark statistics module provides descriptive summaries of repeated load-balancing strategy runs. It calculates the mean, sample standard deviation, minimum, maximum, and number of observations for benchmark metrics.

## Why it exists

Repeated simulation runs can produce different detection rates, false-positive rates, and detection latencies. Descriptive statistics help compare these results across strategies and scenarios. They describe observed results and do not establish statistical significance.

## How to use it

```python
from turncoat_sdn.stats.descriptive import summarize, summarize_metrics

print(summarize([0.7, 0.8, 0.9]))

records = [
    {"strategy": "random", "scenario": "sybil", "detection_rate": 0.7},
    {"strategy": "random", "scenario": "sybil", "detection_rate": 0.8},
]

print(summarize_metrics(records))
```

Run the checks from the repository root:

```bash
pytest tests/stats/test_descriptive.py
pytest
ruff check .
ruff format --check .
```

## How it works inside

### Descriptive statistics

`summarize(values)` returns the observation count, arithmetic mean, sample standard deviation, minimum, and maximum. Sample standard deviation uses the n - 1 denominator and is undefined for fewer than two observations.

### Grouped benchmark statistics

`summarize_metrics(records)` groups records by `strategy` and `scenario` by default. It summarises `detection_rate`, `false_positive_rate`, and `mean_detection_latency_s`. Grouping keys and metric names can be customised.

### Input validation

Non-numeric and non-finite observations are rejected. Records missing grouping keys are rejected. Missing or null metric values are skipped for that metric. Empty input produces null statistics, and a single observation has no sample standard deviation.

## Integration status

This module summarises supplied benchmark records. It does not execute simulations or replace the existing scoring functions.

## Known limits

- Results depend on the supplied benchmark runs.
- Missing values reduce the observation count for the affected metric.
- Descriptive summaries do not establish statistical significance.
- Paired Wilcoxon tests, Holm correction, bootstrap confidence intervals, and replicate aggregation remain separate v0.4 work.
