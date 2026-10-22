import pytest

from turncoat_sdn.scoring.nfr import score_nfr


def test_score_nfr_calculates_rates_and_latency():
    result = score_nfr(
        {
            "offered": 10,
            "failed": 2,
            "slo_violations": 3,
            "latencies_ms": [10, 20, 30, 40],
        }
    )
    assert result["failure_rate"] == pytest.approx(0.2)
    assert result["slo_violation_rate"] == pytest.approx(0.3)
    assert result["mean_latency_ms"] == pytest.approx(25)
    assert result["p95_latency_ms"] == 40


def test_score_nfr_handles_zero_offered():
    result = score_nfr({"offered": 0, "failed": 0, "slo_violations": 0, "latencies_ms": []})
    assert result["failure_rate"] == 0
    assert result["slo_violation_rate"] == 0


def test_score_nfr_rejects_invalid_counts():
    with pytest.raises(ValueError):
        score_nfr({"offered": 2, "failed": 3, "slo_violations": 0, "latencies_ms": []})
