# Results

**Owner:** bv · **Written in:** v0.4

## What it is

A full comparison of the five strategies on every built-in scenario, 30
seeds each, with every metric's mean and its 95% bootstrap confidence
interval. It is the output of one command, reproduced below exactly as it
printed, and it is how to read that output.

## Why it exists

A single run says what happened on one seed. It cannot say whether `zt_sdn`
beats `least_conn`, because a different seed gives different numbers. A
comparison needs the same experiment on many seeds, a mean per strategy, and
an honest statement of how far that mean could move: the confidence interval.
This page is the benchmark doing exactly that, end to end, so anyone can
reproduce it and check our claims.

## How to use it

Reproduce the whole page with one command. It takes about three and a half
minutes on a laptop, and needs no network:

```bash
turncoat replicate -o results.csv --summary summary.csv
```

The defaults are every strategy, every scenario, seeds 1 to 30, 120 s per
run, a 95% interval and 10,000 bootstrap resamples. The same command gives
the same files byte for byte. `results.csv` has one row per run (1,050 rows),
and `summary.csv` one row per strategy, scenario and metric with its mean and
interval. Both formats are in [event-format.md](event-format.md#results-files).

To look at a narrower question, choose what to run:

```bash
turncoat replicate --strategies zt_sdn,no_trust --scenarios grayhole,onoff --seeds 30
turncoat replicate --scenarios both --onset 30 -o late.csv
```

## The comparison

Run on 2026-10-25 from `release-v0.4`:

```
$ turncoat replicate -o results.csv --summary summary.csv
Ran 1,050 runs (5 strategies x 7 scenarios x 30 seeds, 1 to 30) in 211 s
Wrote results.csv (1,050 rows, results format 1.0)
Wrote summary.csv

Mean over seeds, with 95% bootstrap confidence interval [low, high] (10,000 resamples)

clean  (30 seeds per strategy)
                                         random           round_robin            least_conn              no_trust                zt_sdn
  SLO violations (%)          8.68 [8.57, 8.81]     8.22 [8.12, 8.33]  17.60 [16.79, 18.41]     9.67 [9.52, 9.81]     9.11 [8.98, 9.23]
  Failed (%)                  0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.35 [0.25, 0.47]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]
  Routed to attackers (%)     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]
  Mean latency (ms)        207.3 [206.5, 208.1]  200.7 [199.9, 201.4]  298.5 [290.1, 307.2]  218.9 [217.7, 220.0]  212.8 [211.9, 213.6]
  p95 latency (ms)         609.0 [605.6, 612.2]  598.8 [595.4, 602.0]  917.9 [873.9, 965.0]  632.5 [628.5, 636.3]  618.7 [615.1, 622.1]
  Load Gini                0.014 [0.013, 0.015]  0.000 [0.000, 0.000]  0.037 [0.033, 0.040]  0.017 [0.015, 0.019]  0.018 [0.017, 0.020]
  Time to isolate (s)                       n/a                   n/a                   n/a                   n/a                   n/a
  Attackers named (%)                       n/a                   n/a                   n/a                   n/a                   n/a
  Detection latency (s)                     n/a                   n/a                   n/a                   n/a                   n/a
  Honest mislabelled (%)      0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]     0.00 [0.00, 0.00]

sybil  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          14.06 [13.78, 14.34]     12.29 [12.09, 12.49]     28.98 [27.87, 30.24]     11.66 [11.47, 11.84]       9.99 [9.82, 10.17]
  Failed (%)                     0.03 [0.01, 0.05]        0.00 [0.00, 0.00]        3.67 [3.21, 4.18]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]
  Routed to attackers (%)     12.47 [12.34, 12.59]     12.49 [12.49, 12.50]        5.31 [4.60, 6.06]        7.64 [7.49, 7.78]        0.21 [0.19, 0.23]
  Mean latency (ms)           264.9 [260.9, 269.3]     241.3 [239.0, 243.9]     415.8 [402.4, 431.1]     238.8 [237.3, 240.3]     222.7 [221.6, 223.9]
  p95 latency (ms)            859.6 [834.4, 887.8]     760.1 [747.7, 774.0]  1492.0 [1431.5, 1554.1]     702.9 [696.9, 708.9]     639.4 [634.5, 644.0]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.116 [0.108, 0.124]     0.060 [0.058, 0.062]     0.137 [0.136, 0.139]
  Time to isolate (s)               3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]
  Detection latency (s)             3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]

drop  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          19.64 [19.49, 19.79]     19.29 [19.18, 19.39]     26.58 [25.66, 27.51]     13.26 [13.07, 13.44]      10.03 [9.85, 10.22]
  Failed (%)                  12.08 [11.96, 12.21]     12.09 [12.08, 12.10]        6.33 [5.99, 6.71]        3.84 [3.75, 3.92]        0.11 [0.09, 0.13]
  Routed to attackers (%)     12.47 [12.34, 12.59]     12.49 [12.49, 12.50]        5.62 [5.38, 5.90]        3.94 [3.85, 4.02]        0.11 [0.09, 0.13]
  Mean latency (ms)           207.0 [206.1, 208.0]     200.9 [200.0, 201.7]     348.6 [338.6, 358.8]     220.6 [219.4, 221.8]     222.3 [221.0, 223.6]
  p95 latency (ms)            608.2 [604.7, 611.8]     599.0 [594.9, 602.7]  1140.4 [1082.1, 1200.3]     635.8 [631.7, 639.6]     638.6 [634.3, 642.5]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.105 [0.101, 0.109]     0.098 [0.096, 0.099]     0.137 [0.136, 0.139]
  Time to isolate (s)               3.0 [3.0, 3.1]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.4 [3.2, 3.5]
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]
  Detection latency (s)             3.0 [3.0, 3.1]           3.0 [3.0, 3.0]           3.1 [3.0, 3.3]           3.0 [3.0, 3.0]           3.5 [3.3, 3.7]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]

both  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          25.10 [24.79, 25.40]     23.36 [23.16, 23.57]     38.19 [37.24, 39.19]     17.05 [16.75, 17.37]     12.09 [11.85, 12.34]
  Failed (%)                  12.16 [12.04, 12.27]     12.09 [12.08, 12.10]     12.48 [11.91, 13.05]        3.98 [3.90, 4.06]        0.10 [0.09, 0.12]
  Routed to attackers (%)     25.02 [24.85, 25.17]     24.99 [24.99, 24.99]     15.34 [14.32, 16.34]     14.35 [14.19, 14.53]        0.36 [0.33, 0.39]
  Mean latency (ms)           273.1 [268.4, 278.3]     247.1 [244.4, 250.1]     461.1 [449.8, 473.1]     259.9 [256.6, 263.5]     243.6 [241.8, 245.5]
  p95 latency (ms)            899.9 [869.5, 933.7]     785.4 [770.7, 802.0]  1696.8 [1648.2, 1743.2]     788.0 [772.5, 804.4]     684.0 [678.0, 690.0]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.134 [0.124, 0.144]     0.124 [0.122, 0.126]     0.257 [0.256, 0.258]
  Time to isolate (s)               3.1 [3.0, 3.2]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.4 [3.3, 3.6]
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]
  Detection latency (s)             3.0 [3.0, 3.1]           3.0 [3.0, 3.0]           3.1 [3.0, 3.2]           3.0 [3.0, 3.0]           3.2 [3.2, 3.3]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]

grayhole  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                zt_sdn
  SLO violations (%)          19.70 [19.54, 19.84]     19.35 [19.24, 19.45]     25.94 [24.95, 26.98]     13.30 [13.11, 13.48]   10.09 [9.92, 10.26]
  Failed (%)                     9.29 [9.16, 9.43]        9.31 [9.20, 9.40]        4.67 [4.36, 5.00]        2.77 [2.72, 2.83]     0.10 [0.08, 0.13]
  Routed to attackers (%)     12.47 [12.34, 12.59]     12.49 [12.49, 12.50]        6.24 [6.01, 6.49]        5.35 [5.25, 5.45]     0.20 [0.16, 0.26]
  Mean latency (ms)           261.5 [259.8, 263.2]     258.0 [256.3, 259.7]     360.3 [349.9, 371.3]     234.1 [232.4, 235.7]  223.0 [221.6, 224.3]
  p95 latency (ms)            804.1 [792.3, 816.7]     797.0 [785.8, 809.1]  1222.8 [1163.3, 1283.0]     679.0 [673.5, 684.6]  641.7 [637.3, 645.8]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.098 [0.094, 0.103]     0.085 [0.083, 0.087]  0.137 [0.135, 0.139]
  Time to isolate (s)               5.1 [4.5, 5.7]           5.1 [4.4, 5.8]           3.2 [3.0, 3.4]           3.9 [3.5, 4.4]        4.5 [3.7, 5.4]
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  70.00 [53.33, 86.67]
  Detection latency (s)             5.1 [4.5, 5.7]           5.1 [4.4, 5.9]           5.1 [4.3, 5.9]           4.7 [4.1, 5.3]        4.9 [3.8, 6.2]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]     0.00 [0.00, 0.00]

onoff  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)          11.21 [11.03, 11.38]      10.16 [9.98, 10.33]     24.03 [22.94, 25.18]     10.68 [10.50, 10.86]        9.70 [9.55, 9.86]
  Failed (%)                     0.01 [0.00, 0.02]        0.00 [0.00, 0.00]        2.14 [1.84, 2.48]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]
  Routed to attackers (%)     12.47 [12.34, 12.59]     12.49 [12.49, 12.50]       9.89 [9.33, 10.51]     10.15 [10.01, 10.31]        6.70 [6.61, 6.81]
  Mean latency (ms)           232.9 [231.0, 234.9]     219.9 [218.3, 221.6]     363.0 [350.8, 376.0]     229.1 [227.7, 230.5]     219.4 [218.3, 220.5]
  p95 latency (ms)            707.5 [698.7, 716.5]     669.7 [663.0, 676.4]  1244.8 [1175.6, 1318.8]     668.0 [662.4, 673.4]     636.7 [632.2, 641.0]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.064 [0.060, 0.069]     0.037 [0.035, 0.038]     0.071 [0.069, 0.073]
  Time to isolate (s)               3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]           3.0 [3.0, 3.0]
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]
  Detection latency (s)          22.0 [22.0, 22.0]        22.0 [22.0, 22.0]        22.0 [22.0, 22.0]        22.0 [22.0, 22.0]        22.0 [22.0, 22.0]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]

spoof  (30 seeds per strategy)
                                            random              round_robin               least_conn                 no_trust                   zt_sdn
  SLO violations (%)             8.68 [8.57, 8.81]        8.22 [8.12, 8.33]     17.60 [16.79, 18.41]        9.67 [9.52, 9.81]        9.11 [8.98, 9.23]
  Failed (%)                     0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.35 [0.25, 0.47]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]
  Routed to attackers (%)        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]
  Mean latency (ms)           207.3 [206.5, 208.1]     200.7 [199.9, 201.4]     298.5 [290.1, 307.2]     218.9 [217.7, 220.0]     212.8 [211.9, 213.6]
  p95 latency (ms)            609.0 [605.6, 612.2]     598.8 [595.4, 602.0]     917.9 [873.9, 965.0]     632.5 [628.5, 636.3]     618.7 [615.1, 622.1]
  Load Gini                   0.014 [0.013, 0.015]     0.000 [0.000, 0.000]     0.037 [0.033, 0.040]     0.017 [0.015, 0.019]     0.018 [0.017, 0.020]
  Time to isolate (s)                          n/a                      n/a                      n/a                      n/a                      n/a
  Attackers named (%)      100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]  100.00 [100.00, 100.00]
  Detection latency (s)             0.0 [0.0, 0.0]           0.0 [0.0, 0.0]           0.0 [0.0, 0.0]           0.0 [0.0, 0.0]           0.0 [0.0, 0.0]
  Honest mislabelled (%)         0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]        0.00 [0.00, 0.00]
```

The first rows of `results.csv`:

```
strategy,scenario,seed,offered,completed,failed,slo_violation_rate,failure_rate,malicious_share,mean_latency_ms,p95_latency_ms,gini,time_to_isolate_s,attackers,attackers_named,detection_rate,mean_detection_latency_s,honest_subjects,honest_mislabelled,false_positive_rate
random,clean,1,7624,7615,0,0.081847,0.0,0.0,204.562,591.966,0.0106,,0,0,,,8,0,0.0
round_robin,clean,1,7624,7615,0,0.079879,0.0,0.0,199.47,585.769,0.0,,0,0,,,8,0,0.0
```

## How to read it

Each cell is `mean [low, high]`: the mean over the 30 seeds, and the range
that the percentile bootstrap gives 95% coverage (see
[statistics.md](statistics.md#confidence-intervals)). Rates are percentages.
`n/a` means no run could measure the metric: there is no attacker to detect
in `clean`, and nothing is isolated when the attack is refused at admission
(`spoof`).

**What it shows.**

- **Trust pays where there is an attacker, and costs little where there is
  not.** Against `both`, `zt_sdn` holds SLO violations to 12.09%
  [11.85, 12.34] against `round_robin`'s 23.36% [23.16, 23.57] and fails
  0.10% of tasks against 12.09%. In `clean` it pays 9.11% [8.98, 9.23]
  against `round_robin`'s 8.22% [8.12, 8.33]: the load-staleness cost of the
  1 s poll (see [simulator.md](simulator.md#known-limits)).
- **Every strategy's controller names the attackers; only `zt_sdn` acts on
  it.** Detection is the controller's, the same for every strategy, which is
  why "Attackers named" is near 100% across the row. What differs is "Routed
  to attackers": an eighth of all traffic for the trust-blind strategies
  against a sybil, 0.21% [0.19, 0.23] for `zt_sdn`.
- **`least_conn` is the worst strategy under attack**, worse than random.
  A dropper and a Sybil both look idle to it, so it feeds them: 38.19%
  [37.24, 39.19] SLO violations in `both`.
- **On-off is the attack trust contains least.** `zt_sdn` still sends it
  6.70% [6.61, 6.81] of traffic, because every honest phase readmits it, and
  it is named 22.0 s after onset on every seed: one full 20 s period plus the
  tell's reaction.
- **`zt_sdn` names the grayhole less often than the others: 70.00%
  [53.33, 86.67].** It is the only strategy that quarantines on trust. On 7
  of 30 seeds trust isolates the grayhole before the timeout-rate tell has
  enough outcomes to fire, so nothing names it (see
  [attacks.md](attacks.md#known-limits)); on 2 more its timeout rate reads as
  a blackhole's. Its interval is wide because a per-run detection rate here
  is 0 or 1. The other strategies keep routing to the grayhole, so the tell
  always gets its samples.
- **`spoof` costs nothing in service**, row for row the same as `clean`: the
  spoofed requests are refused at admission and never reach a server.

**What it does not show.** Two intervals that do not overlap make a
difference likely; two that overlap do not rule one out. The runs are
paired, the same seed gives every strategy the same workload, and a paired
test uses that pairing where side-by-side intervals cannot. That is the
Wilcoxon signed-rank test with Holm correction in
[statistics.md](statistics.md), and `turncoat compare` reads `results.csv`
to run it.

## How it works inside

`turncoat replicate` runs scenario by scenario, seed by seed, strategy by
strategy, the order `run_paired` uses. Each run has the controller view
`turncoat run` gives: the real trust calculator and the latency tell. Its
recording is kept in memory (`turncoat_sdn.events.EventList`), scored with
the same attack scorer `turncoat score` uses, and reduced to one row: the
simulator's thirteen columns plus seven detection columns. Rows go to
`results.csv`, and `turncoat_sdn.stats.bootstrap_metrics` puts an interval on
each metric for each strategy and scenario.

Every interval is resampled with the same seed. Groups of the same size draw
the same resample indices, so the strategies are resampled seed for seed,
the way they were run.

## Known limits

- **Thirty seeds, one fleet.** Every number is for the default 8-node fleet
  at 40% load. Other sizes and loads are a `SimConfig` away, but not yet a
  `replicate` option.
- **Intervals at the edges collapse.** When every run agrees, as with a
  detection rate of 100% on every seed, the interval is the mean:
  `100.00 [100.00, 100.00]`. That is what the data says, not certainty that
  the next seed agrees.
- **The percentile bootstrap runs a little narrow at small n.** At 30 seeds
  its coverage is close to 95%; at 5 seeds it is noticeably less. Use 30.
- **Detection latency averages named attackers only.** A strategy that names
  fewer attackers is averaged over fewer runs; check the "Attackers named"
  row beside it.
