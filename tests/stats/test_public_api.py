"""Public exports from the statistics package."""


def test_paired_api_is_exported():
    from turncoat_sdn.stats import (
        PairedComparison,
        holm_adjust,
        paired_wilcoxon,
    )

    assert PairedComparison.__name__ == "PairedComparison"
    assert callable(holm_adjust)
    assert callable(paired_wilcoxon)


def test_public_holm_adjust_is_usable():
    from turncoat_sdn.stats import holm_adjust

    assert holm_adjust([0.01, 0.04]) == (0.02, 0.04)
