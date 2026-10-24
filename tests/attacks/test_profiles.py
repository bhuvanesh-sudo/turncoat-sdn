"""The attack profile interface, and Sybil and Blackhole on it.

These test the profiles on their own, with no simulator: the onset rule in
``ServerAttack``, and what each attack does once it has turned.
"""

from __future__ import annotations

import random

import pytest

from turncoat_sdn.attacks import Blackhole, ServerAttack, Status, Sybil

RNG = random.Random(0)
HONEST = Status(claimed_cpu=0.75, rtt_ms=52.5)
JITTER = 2.5  # HONEST.rtt_ms is the 50 ms base plus this


class Slow(ServerAttack):
    """The smallest possible attack: serve three times slower."""

    name = "slow"

    def serve(self, now, demand_s, rng):
        return demand_s * 3


class TestOnset:
    def test_honest_before_onset(self):
        attack = Slow(start_s=10.0)
        assert not attack.active(9.999)
        assert attack.service_time(9.999, 0.2, RNG) == 0.2
        assert attack.status(9.999, HONEST, JITTER, RNG) == HONEST

    def test_hostile_from_onset(self):
        attack = Slow(start_s=10.0)
        assert attack.active(10.0)
        assert attack.service_time(10.0, 0.2, RNG) == pytest.approx(0.6)

    def test_default_onset_is_the_first_second(self):
        assert Slow().start_s == 0.0
        assert Slow().active(0.0)

    def test_unoverridden_methods_stay_honest_after_onset(self):
        # Slow only overrides serve, so it reports like an honest server.
        assert Slow().status(50.0, HONEST, JITTER, RNG) == HONEST

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "10"])
    def test_rejects_a_bad_onset(self, bad):
        with pytest.raises(ValueError, match="start_s"):
            Slow(start_s=bad)

    def test_an_attack_must_name_itself(self):
        class Nameless(ServerAttack):
            pass

        with pytest.raises(TypeError, match="name"):
            Nameless()

    def test_ground_truth_is_the_label_and_the_onset(self):
        assert Slow(start_s=12.5).ground_truth() == {"attack": "slow", "attack_start_s": 12.5}

    def test_one_instance_serves_many_runs(self):
        # Nothing about a run is kept on the profile, so asking twice gives the
        # same answer.
        attack = Sybil(start_s=5.0)
        first = [attack.status(t, HONEST, JITTER, RNG) for t in (1.0, 6.0)]
        again = [attack.status(t, HONEST, JITTER, RNG) for t in (1.0, 6.0)]
        assert first == again


class TestSybil:
    def test_lies_and_answers_slowly_after_onset(self):
        assert Sybil().status(1.0, HONEST, JITTER, RNG) == Status(0.1, 220.0 + JITTER)

    def test_serves_every_task_slowly_but_never_drops_one(self):
        assert Sybil().service_time(1.0, 0.2, RNG) == pytest.approx(0.4)

    def test_settings(self):
        sybil = Sybil(3.0, claimed_cpu=0.05, slowdown=1.5, rtt_ms=180.0)
        assert sybil.status(4.0, HONEST, JITTER, RNG) == Status(0.05, 180.0 + JITTER)
        assert sybil.service_time(4.0, 0.2, RNG) == pytest.approx(0.3)
        assert sybil.ground_truth() == {"attack": "sybil", "attack_start_s": 3.0}

    @pytest.mark.parametrize(
        "kwargs",
        [{"claimed_cpu": 1.5}, {"claimed_cpu": -0.1}, {"slowdown": 0.0}, {"rtt_ms": -1.0}],
    )
    def test_rejects_bad_settings(self, kwargs):
        with pytest.raises(ValueError):
            Sybil(**kwargs)

    def test_honest_before_onset(self):
        sybil = Sybil(start_s=30.0)
        assert sybil.status(29.0, HONEST, JITTER, RNG) == HONEST
        assert sybil.service_time(29.0, 0.2, RNG) == 0.2


class TestBlackhole:
    def test_drops_every_task_after_onset(self):
        assert Blackhole().service_time(1.0, 0.2, RNG) is None

    def test_still_reports_honestly(self):
        # Prompt, truthful polls are what keep its trust at ~0.36: only the
        # timeout-rate tell can isolate it.
        assert Blackhole().status(1.0, HONEST, JITTER, RNG) == HONEST

    def test_keeps_the_label_earlier_releases_recorded(self):
        assert Blackhole(4.0).ground_truth() == {"attack": "drop", "attack_start_s": 4.0}

    def test_serves_before_onset(self):
        assert Blackhole(start_s=30.0).service_time(29.0, 0.2, RNG) == 0.2


def test_repr_shows_the_onset():
    assert repr(Blackhole(7.0)) == "Blackhole(start_s=7)"
    assert "start_s=7" in repr(Sybil(7.0))
