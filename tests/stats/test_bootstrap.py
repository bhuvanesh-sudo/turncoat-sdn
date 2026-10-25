"""Percentile-bootstrap confidence intervals: seeded, honest at the edges, and calibrated."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from turncoat_sdn.stats import ConfidenceInterval, bootstrap_ci, bootstrap_metrics
from turncoat_sdn.stats.descriptive import summarize_metrics

VALUES = [0.12, 0.10, 0.15, 0.11, 0.09, 0.14, 0.13, 0.10, 0.16, 0.12]


class TestBootstrapCI:
    def test_mean_with_bounds_around_it(self):
        ci = bootstrap_ci(VALUES)
        assert ci.mean == pytest.approx(sum(VALUES) / len(VALUES))
        assert ci.low < ci.mean < ci.high
        assert min(VALUES) <= ci.low and ci.high <= max(VALUES)
        assert (ci.n, ci.confidence, ci.resamples) == (10, 0.95, 10_000)

    def test_is_the_percentile_bootstrap(self):
        ci = bootstrap_ci(VALUES, resamples=2_000, seed=7)
        rng = np.random.default_rng(7)
        data = np.asarray(VALUES)
        means = data[rng.integers(0, len(data), size=(2_000, len(data)))].mean(axis=1)
        assert (ci.low, ci.high) == tuple(np.quantile(means, [0.025, 0.975]))

    def test_seeded(self):
        rng = random.Random(2)
        values = [rng.random() for _ in range(25)]
        assert bootstrap_ci(values, seed=3) == bootstrap_ci(values, seed=3)
        assert bootstrap_ci(values, seed=3) != bootstrap_ci(values, seed=4)

    def test_wider_at_higher_confidence_and_narrower_with_more_runs(self):
        ci90 = bootstrap_ci(VALUES, confidence=0.90)
        ci99 = bootstrap_ci(VALUES, confidence=0.99)
        assert ci99.high - ci99.low > ci90.high - ci90.low
        more = bootstrap_ci(VALUES * 4)
        base = bootstrap_ci(VALUES)
        assert more.high - more.low < base.high - base.low

    def test_covers_the_true_mean_about_95_percent_of_the_time(self):
        # 300 samples of 30 runs from a skewed distribution with mean 1.0.
        rng = random.Random(11)
        covered = 0
        for trial in range(300):
            sample = [rng.expovariate(1.0) for _ in range(30)]
            ci = bootstrap_ci(sample, resamples=2_000, seed=trial)
            covered += ci.low <= 1.0 <= ci.high
        assert 0.88 <= covered / 300 <= 0.98

    def test_no_runs(self):
        ci = bootstrap_ci([])
        assert (ci.mean, ci.low, ci.high, ci.n) == (None, None, None, 0)
        assert ci.format() == "n/a"

    @pytest.mark.parametrize("values", [[0.4], [0.25, 0.25, 0.25]])
    def test_one_run_or_runs_that_agree(self, values):
        ci = bootstrap_ci(values)
        assert ci.mean == ci.low == ci.high == values[0]

    def test_skips_runs_that_could_not_measure_it(self):
        assert bootstrap_ci([0.5, None, "", 1.0]).n == 2

    @pytest.mark.parametrize("bad", [True, "0.5", float("nan"), math.inf])
    def test_rejects_non_numbers(self, bad):
        with pytest.raises((TypeError, ValueError)):
            bootstrap_ci([0.1, bad])

    @pytest.mark.parametrize(
        "kwargs", [{"confidence": 0}, {"confidence": 1}, {"resamples": 0}, {"resamples": 1.5}]
    )
    def test_rejects_bad_settings(self, kwargs):
        with pytest.raises(ValueError):
            bootstrap_ci(VALUES, **kwargs)

    def test_format(self):
        ci = ConfidenceInterval(0.1234, 0.1, 0.15, 10, 0.95, 100)
        assert ci.format() == "0.1234 [0.1, 0.15]"
        assert ci.format(".2f") == "0.12 [0.10, 0.15]"


class TestBootstrapMetrics:
    ROWS = [
        {"strategy": "zt_sdn", "scenario": "both", "slo": 0.10, "lat": 3.0},
        {"strategy": "random", "scenario": "both", "slo": 0.20, "lat": None},
        {"strategy": "zt_sdn", "scenario": "both", "slo": 0.12, "lat": 4.0},
        {"strategy": "random", "scenario": "both", "slo": 0.22, "lat": None},
    ]

    def test_one_interval_per_metric_per_group_in_first_seen_order(self):
        groups = bootstrap_metrics(self.ROWS, ["slo", "lat"])
        assert [(g["strategy"], g["runs"]) for g in groups] == [("zt_sdn", 2), ("random", 2)]
        assert groups[0]["slo"].mean == pytest.approx(0.11)
        assert groups[1]["lat"].n == 0

    def test_groups_of_the_same_size_are_resampled_run_for_run(self):
        # Same seed and size: the same resample indices, so a constant
        # difference between groups shows up as the same shift in the bounds.
        groups = bootstrap_metrics(
            [{"strategy": "a", "scenario": "s", "m": v} for v in VALUES]
            + [{"strategy": "b", "scenario": "s", "m": v + 1.0} for v in VALUES],
            ["m"],
        )
        a, b = groups[0]["m"], groups[1]["m"]
        assert b.low - a.low == pytest.approx(1.0)
        assert b.high - a.high == pytest.approx(1.0)

    def test_rejects_rows_without_the_grouping_keys(self):
        with pytest.raises(ValueError, match="grouping keys"):
            bootstrap_metrics([{"strategy": "a", "m": 1.0}], ["m"])


class TestDescriptiveSummaries:
    RECORDS = [
        {"strategy": "random", "scenario": "sybil", "detection_rate": v} for v in (0.5, 1.0, 0.75)
    ]

    def test_unchanged_without_a_confidence_level(self):
        summary = summarize_metrics(self.RECORDS)[0]["detection_rate"]
        assert set(summary) == {"count", "mean", "sample_stddev", "minimum", "maximum"}

    def test_adds_an_interval_with_one(self):
        summary = summarize_metrics(self.RECORDS, confidence=0.95)[0]["detection_rate"]
        interval = bootstrap_ci([0.5, 1.0, 0.75])
        assert (summary["ci_low"], summary["ci_high"]) == (interval.low, interval.high)
        assert summary["ci_low"] <= summary["mean"] <= summary["ci_high"]
