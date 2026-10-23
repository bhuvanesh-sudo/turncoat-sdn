import pytest

from turncoat_sdn.scoring.availability import score_availability


def test_availability_uses_completed_over_offered():
    result = score_availability({"offered": 10, "completed": 9})
    assert result["availability"] == pytest.approx(0.9)
    assert result["uncompleted"] == 1


def test_availability_handles_zero_offered():
    assert score_availability({"offered": 0, "completed": 0})["availability"] == 0


def test_availability_rejects_completed_above_offered():
    with pytest.raises(ValueError):
        score_availability({"offered": 2, "completed": 3})
