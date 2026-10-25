"""Tests for paired comparisons and Holm correction."""

import math

import pytest

from turncoat_sdn.stats.paired import holm_adjust, paired_wilcoxon


def make_rows(a, b, *, scenario="both", metric="slo_violation_rate"):
    rows = []
    for seed, value in enumerate(a, start=1):
        rows.append({"strategy": "a", "scenario": scenario, "seed": seed, metric: value})
    for seed, value in enumerate(b, start=1):
        rows.append({"strategy": "b", "scenario": scenario, "seed": seed, metric: value})
    return rows


class TestPairedWilcoxon:
    def test_matched_pairs_and_effect_summary(self):
        result = paired_wilcoxon(
            make_rows([1, 2, 3, 4], [2, 3, 4, 5]), "a", "b", "both", "slo_violation_rate"
        )
        assert result.n_pairs == 4
        assert result.n_missing_pairs == 0
        assert result.mean_difference == pytest.approx(-1)
        assert result.median_difference == pytest.approx(-1)
        assert result.p_value == pytest.approx(0.125)

    def test_input_order_does_not_change_pairing(self):
        rows = make_rows([1, 2, 3], [3, 2, 1])
        result = paired_wilcoxon(list(reversed(rows)), "a", "b", "both", "slo_violation_rate")
        assert result.n_pairs == 3
        assert result.mean_difference == pytest.approx(0)

    def test_missing_metric_excludes_whole_pair(self):
        result = paired_wilcoxon(
            make_rows([1, None, 3], [2, 2, 4]), "a", "b", "both", "slo_violation_rate"
        )
        assert result.n_pairs == 2
        assert result.n_missing_pairs == 1

    def test_all_zero_differences_return_p_one(self):
        result = paired_wilcoxon(
            make_rows([2, 2, 2], [2, 2, 2]), "a", "b", "both", "slo_violation_rate"
        )
        assert result.statistic == 0
        assert result.p_value == 1

    def test_unmatched_seed_sets_are_rejected(self):
        rows = make_rows([1, 2], [2, 3])
        rows = [row for row in rows if not (row["strategy"] == "b" and row["seed"] == 2)]
        with pytest.raises(ValueError, match="matching seeds"):
            paired_wilcoxon(rows, "a", "b", "both", "slo_violation_rate")

    def test_duplicate_seed_is_rejected(self):
        rows = make_rows([1, 2], [2, 3])
        rows.append(rows[0])
        with pytest.raises(ValueError, match="duplicate row"):
            paired_wilcoxon(rows, "a", "b", "both", "slo_violation_rate")

    def test_no_rows_are_rejected(self):
        with pytest.raises(ValueError, match="no rows found"):
            paired_wilcoxon([], "a", "b", "both", "metric")

    def test_no_complete_pairs_are_rejected(self):
        with pytest.raises(ValueError, match="no complete pairs"):
            paired_wilcoxon(make_rows([None], [1]), "a", "b", "both", "slo_violation_rate")

    @pytest.mark.parametrize("bad", [True, "1", math.inf, math.nan])
    def test_invalid_metric_values_are_rejected(self, bad):
        with pytest.raises((TypeError, ValueError)):
            paired_wilcoxon(make_rows([bad], [1]), "a", "b", "both", "slo_violation_rate")

    def test_same_strategy_is_rejected(self):
        with pytest.raises(ValueError, match="different"):
            paired_wilcoxon([], "a", "a", "both", "metric")


class TestHolmAdjust:
    def test_known_example_preserves_original_order(self):
        assert holm_adjust([0.01, 0.04, 0.03, 0.002]) == pytest.approx([0.03, 0.06, 0.06, 0.008])

    def test_adjusted_values_are_monotonic_when_sorted_by_raw_p(self):
        raw = [0.04, 0.001, 0.03, 0.02]
        adjusted = holm_adjust(raw)
        ordered = sorted(zip(raw, adjusted, strict=True))
        assert [value for _, value in ordered] == sorted(value for _, value in ordered)

    def test_empty_input(self):
        assert holm_adjust([]) == ()

    @pytest.mark.parametrize("bad", [-0.1, 1.1, math.inf, math.nan])
    def test_invalid_p_values_are_rejected(self, bad):
        with pytest.raises(ValueError):
            holm_adjust([bad])

    @pytest.mark.parametrize("bad", [True, "0.5"])
    def test_non_numeric_p_values_are_rejected(self, bad):
        with pytest.raises(TypeError):
            holm_adjust([bad])

    def test_single_p_value_is_unchanged(self):
        assert holm_adjust([0.03]) == pytest.approx([0.03])


class TestPairedWilcoxonEdgeCases:
    @pytest.mark.parametrize(
        ("strategy_a", "strategy_b", "scenario", "metric"),
        [
            ("", "b", "both", "metric"),
            ("a", " ", "both", "metric"),
            ("a", "b", "", "metric"),
            ("a", "b", "both", " "),
        ],
    )
    def test_empty_labels_are_rejected(self, strategy_a, strategy_b, scenario, metric):
        with pytest.raises(ValueError, match="non-empty"):
            paired_wilcoxon([], strategy_a, strategy_b, scenario, metric)

    @pytest.mark.parametrize("alternative", ["invalid", "", None])
    def test_unsupported_alternative_is_rejected(self, alternative):
        with pytest.raises(ValueError, match="alternative"):
            paired_wilcoxon(
                [],
                "a",
                "b",
                "both",
                "metric",
                alternative=alternative,
            )

    @pytest.mark.parametrize("seed", [True, 1.5, "1", None])
    def test_invalid_seed_types_are_rejected(self, seed):
        rows = make_rows([1], [2])
        rows[0]["seed"] = seed
        with pytest.raises(TypeError, match="seed"):
            paired_wilcoxon(rows, "a", "b", "both", "slo_violation_rate")

    def test_missing_required_row_key_is_rejected(self):
        with pytest.raises(ValueError, match="required keys"):
            paired_wilcoxon(
                [{"strategy": "a", "scenario": "both"}],
                "a",
                "b",
                "both",
                "metric",
            )


class TestHolmAdjustEdgeCases:
    def test_tied_p_values_are_adjusted_consistently(self):
        assert holm_adjust([0.01, 0.01, 0.5]) == pytest.approx([0.03, 0.03, 0.5])

    def test_boundary_p_values_are_supported(self):
        assert holm_adjust([0.0, 1.0]) == pytest.approx([0.0, 1.0])

    def test_all_equal_p_values_receive_holm_adjustment(self):
        assert holm_adjust([0.2, 0.2, 0.2]) == pytest.approx([0.6, 0.6, 0.6])
