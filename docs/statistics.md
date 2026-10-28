# Statistics

**Owner:** arv · **Written in:** v0.4

## What it is

`turncoat_sdn.stats` turns many runs into claims you can defend. It has three
parts:

| Part | Answers | Module | Status |
|---|---|---|---|
| Descriptive summaries | What were the mean, spread and range over the runs? | `stats/descriptive.py` | v0.3, see [benchmark-statistics.md](benchmark-statistics.md) |
| [Confidence intervals](#confidence-intervals) | How far could each mean move on other seeds? | `stats/bootstrap.py` | v0.4 |
| [Paired tests](paired-statistics.md) | How do two strategies compare on matched seeds? | `stats/paired.py` | v0.4 implemented |
| [Robustness rankings](#robustness-rankings) | Which strategy holds up best across every scenario? | `stats/robustness.py` | v1.0 |

They all read the same input, the results file `turncoat replicate` writes:
one row per run, every metric a column (see
[event-format.md](event-format.md#results-files)).

## Why it exists

A benchmark that prints one number per strategy invites the wrong question
("which number is bigger?"). The right question is whether the difference
would survive another set of seeds. An interval says how precise each mean
is; a paired test says whether a difference is real. Both need many seeds,
and the simulator's paired seeds make the test far more sensitive than
comparing two separate samples.

## How to use it

From the command line, `turncoat replicate` prints every metric with its
interval (a full example is in [results.md](results.md)):

```bash
turncoat replicate --scenarios both --seeds 30 -o results.csv
```

From Python, read the results file and ask for intervals:

```python
from turncoat_sdn.stats import RESULT_METRICS, bootstrap_ci, bootstrap_metrics, read_results

rows = read_results("results.csv")
for group in bootstrap_metrics(rows, list(RESULT_METRICS)):
    print(group["strategy"], group["scenario"], group["slo_violation_rate"].format(".4f"))
# random both 0.2510 [0.2479, 0.2540]
# round_robin both 0.2336 [0.2316, 0.2357]
# least_conn both 0.3819 [0.3724, 0.3919]
# no_trust both 0.1705 [0.1675, 0.1737]
# zt_sdn both 0.1209 [0.1185, 0.1234]

zt = [r["slo_violation_rate"] for r in rows if r["strategy"] == "zt_sdn"]
print(bootstrap_ci(zt, confidence=0.99).format(".4f"))
# 0.1209 [0.1178, 0.1241]
```

`summarize_metrics(records, confidence=0.95)` in `stats/descriptive.py` adds
the same interval, as `ci_low` and `ci_high`, to each descriptive summary.

## Confidence intervals

### What is computed

For each metric, in each strategy and scenario, the mean over runs and a
**percentile-bootstrap** interval around it:

1. Resample the runs with replacement, as many as there are, and take the
   mean. Do that 10,000 times.
2. The interval is the 2.5th to the 97.5th percentile of those means, for
   95% coverage.

The bootstrap assumes nothing about the metric's distribution. That matters
here: rates pile up at 0 or at 1, latencies are skewed, and a detection rate
over one attacker is 0 or 1 per run. A normal-theory interval can run past
0% or 100%; a percentile interval cannot leave the range of the data.

### Settings

| Setting | Default | `replicate` option | Notes |
|---|---|---|---|
| Confidence | 0.95 | `--confidence` | Any level strictly between 0 and 1 |
| Resamples | 10,000 | `--resamples` | Monte Carlo error on a bound is well under its sampling error at 30 runs |
| Seed | 0 | none | Fixed, so the same runs give the same interval every time |

### What it does with awkward data

| Data | Interval |
|---|---|
| No runs could measure it (no attacker in `clean`, a blank cell) | `None`, printed `n/a`. Blank cells are skipped, never read as 0. |
| One run, or every run agrees | The mean itself: `100.00 [100.00, 100.00]` |
| A non-number, `NaN` or infinity | Rejected with an error, not skipped |

### Paired resampling

The resampling seed is the same for every group, so two groups with the same
number of runs draw the same resample indices. Strategies run on the same
seeds are therefore resampled seed for seed, the way they were run, and a
constant difference between two strategies moves both bounds by exactly that
difference. A test pins it.

### In code

| Function | Returns |
|---|---|
| `bootstrap_ci(values, *, confidence, resamples, seed)` | A `ConfidenceInterval`: `mean`, `low`, `high`, `n`, `confidence`, `resamples`, and `format(spec)` for `mean [low, high]` |
| `bootstrap_metrics(rows, metrics, *, group_by, ...)` | One dict per group: the grouping values, `runs`, and a `ConfidenceInterval` per metric |

`tests/stats/test_bootstrap.py` checks the method against a direct numpy
computation, the edge cases, and calibration: on 300 samples of 30 runs from
a skewed distribution, the 95% interval covers the true mean between 88% and
98% of the time.

## Paired tests

Paired Wilcoxon signed-rank testing and Holm-Bonferroni p-value correction
are implemented in `stats/paired.py` and exported from `turncoat_sdn.stats`.
See [Paired Benchmark Statistics](paired-statistics.md) for the API, examples,
validation rules, test commands, integration status, and known limitations.

## Robustness rankings

### What it is

`rank_strategies` answers a different question from the paired tests: not
"is A better than B in this scenario?" but "which strategy holds up best
across all of them?". It ranks the strategies on one metric within each
scenario, then ranks them overall by their average rank. It lives in
`stats/robustness.py` and is exported from `turncoat_sdn.stats`.

### How to use it

It reads the same results file as everything else on this page:

```python
from turncoat_sdn.stats import rank_strategies, read_results

rows = read_results("results.csv")
ranking = rank_strategies(rows, metric="slo_violation_rate")

for row in ranking["overall_rankings"]:
    print(
        f"{row['strategy']:<12} average rank {row['average_rank']:.2f}"
        f"  (spread {row['rank_stddev']:.2f} over {row['scenarios_ranked']} scenarios)"
    )

both = next(s for s in ranking["scenario_rankings"] if s["scenario"] == "both")
print(both["ranks"])
```

On a results file from `turncoat replicate --seeds 10 -o results.csv` (all
five strategies, all seven scenarios, 350 runs):

```
zt_sdn       average rank 1.57  (spread 0.90 over 7 scenarios)
round_robin  average rank 2.29  (spread 0.88 over 7 scenarios)
no_trust     average rank 2.71  (spread 0.88 over 7 scenarios)
random       average rank 3.43  (spread 0.90 over 7 scenarios)
least_conn   average rank 5.00  (spread 0.00 over 7 scenarios)
{'least_conn': 5.0, 'no_trust': 2.0, 'random': 4.0, 'round_robin': 3.0, 'zt_sdn': 1.0}
```

`zt_sdn` has the best average rank on SLO violations, and its spread says
it is not first everywhere: `round_robin` beats it in `clean` and `spoof`,
where no server attacks (see [results.md](results.md)). `least_conn` is last
in every one of the seven scenarios, so its spread is zero.

### How it works inside

1. Each strategy's metric is averaged over its seeds within each scenario.
   Blank cells (a metric the run could not measure) are skipped.
2. Strategies are ranked within each scenario in the metric's own direction,
   taken from `RESULT_METRICS`: lower is better for SLO violations, higher
   for attackers named. Ties share the average of the ranks they span, so
   two strategies tied for first both get 1.5.
3. Each strategy's overall score is the mean of its per-scenario ranks, and
   `rank_stddev` is their population standard deviation. The overall list is
   sorted by average rank, then by name.

The result is a plain dict: `metric`, `higher_is_better`, `scenarios`,
`scenario_rankings` (each scenario's `metric_means` and `ranks`) and
`overall_rankings` (each strategy's `average_rank`, `rank_stddev` and
`scenarios_ranked`). Pass `scenarios=[...]` to rank over a subset.

### Known limits

- **Ranks hide the size of a gap.** A strategy that is second by 0.01 points
  and one that is second by 10 points rank the same. Read the ranking beside
  the means, or the paired tests, before calling one strategy better.
- **No uncertainty.** The ranking uses seed means only, with no interval or
  test. Two strategies whose intervals overlap can still rank differently.
- **Every strategy must be measured in every scenario.** A scenario where a
  strategy has no valid value for the metric raises `ValueError`; time to
  isolate in `clean` is one, so pass `scenarios=` to leave such scenarios out.
- **Python only.** There is no `turncoat` command for it yet.
