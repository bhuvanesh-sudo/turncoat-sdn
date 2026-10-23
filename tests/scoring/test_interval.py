import pytest

from turncoat_sdn.scoring.interval import score_intervals


def test_interval_scoring_groups_and_averages_samples():
    result = score_intervals(
        [
            {"timestamp_s": 0.5, "latency_ms": 10},
            {"timestamp_s": 1.5, "latency_ms": 20},
            {"timestamp_s": 1.8, "latency_ms": 40},
        ],
        interval_s=1.0,
    )
    assert len(result) == 2
    assert result[0]["latency_ms"] == 10
    assert result[1]["latency_ms"] == 30


def test_interval_scoring_rejects_invalid_width():
    with pytest.raises(ValueError):
        score_intervals([], interval_s=0)
