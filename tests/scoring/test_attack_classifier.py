"""The attack classifier, moved from ``controller/attack_classifier.py``.

Ported from the final-year project's ``tests/test_attack_classifier.py`` with
the import paths changed and unittest assertions written as plain asserts.
The interesting cases are the two pairs that a single detection cycle cannot
separate -- blackhole/grayhole (magnitude) and sybil/onoff (intermittency) --
plus the abstention rules, which keep the classifier from re-asserting stale
verdicts.

One test stays behind: the check that ``simulation/topology.py``'s on-off
default clears the detectability floor reads a live-testbed file. It moves
with the Mininet backend in v1.0.
"""

from __future__ import annotations

import pytest

from turncoat_sdn.scoring.attack_classifier import (
    ATTACK_BAD_CREDENTIALS,
    ATTACK_BLACKHOLE,
    ATTACK_FLOOD,
    ATTACK_GRAYHOLE,
    ATTACK_ONOFF,
    ATTACK_SPOOF,
    ATTACK_SYBIL,
    DEFAULT_BLACKHOLE_MIN_RATE,
    DEFAULT_EVIDENCE_MAX_AGE_S,
    DEFAULT_MIN_CLEAN_RUN,
    DEFAULT_MIN_LYING_SHARE,
    DEFAULT_MIN_QUIET_FRACTION,
    NODE_DOWN,
    ONOFF_MIN_GOOD_PHASE_S,
    SIG_AUTH_BAD_RESPONSE,
    SIG_AUTH_IP_PIN,
    SIG_CPU_HONESTY,
    SIG_FLOOD,
    SIG_LATENCY_TELL,
    SIG_PACKET_DROP,
    SIG_TRUST_COLLAPSE,
    SIG_UNREACHABLE,
    AttackEvidence,
    Observation,
    classify_client,
    classify_node,
    family_of,
)


def window(pattern, start=0.0, step=1.0):
    """Build a window from a list of signal dicts, one per cycle."""
    return [Observation(start + i * step, sig) for i, sig in enumerate(pattern)]


CLEAN = {}


class TestAbstention:
    def test_empty_window_abstains(self):
        assert classify_node([]) is None
        assert classify_client([]) is None

    def test_all_clean_abstains_rather_than_declaring_innocence(self):
        assert classify_node(window([CLEAN] * 20)) is None

    def test_stale_evidence_abstains_instead_of_reasserting(self):
        w = window([{SIG_LATENCY_TELL: 6.0}] * 10)
        last_t = w[-1].t
        # Fresh: a verdict.
        assert classify_node(w, now=last_t + 1.0) is not None
        # Stale: no opinion. A detector with no recent evidence must abstain,
        # not re-assert its last verdict.
        assert classify_node(w, now=last_t + DEFAULT_EVIDENCE_MAX_AGE_S + 1.0) is None

    def test_offline_replay_skips_the_staleness_clock(self):
        w = window([{SIG_LATENCY_TELL: 6.0}] * 10)
        # now=None is what the offline scorer passes: the run is over, so
        # "stale" is not a meaningful question.
        assert classify_node(w, now=None) is not None


class TestSybilVsOnOff:
    def test_sustained_lying_is_sybil(self):
        w = window([CLEAN] * 5 + [{SIG_LATENCY_TELL: 6.0}] * 30)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_cpu_honesty_alone_is_also_the_sybil_family(self):
        w = window([{SIG_CPU_HONESTY: 0.62}] * 20)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_intermittent_lying_is_onoff(self):
        bad = [{SIG_LATENCY_TELL: 5.5}] * 8
        good = [CLEAN] * 8
        result = classify_node(window(bad + good + bad + good + bad))
        assert result.attack_type == ATTACK_ONOFF
        assert "interrupted by" in result.rationale

    def test_clean_run_shorter_than_the_floor_stays_sybil(self):
        # A gap of DEFAULT_MIN_CLEAN_RUN - 1 clean cycles is jitter, not an
        # off phase. Without this a noisy sybil would be relabelled on-off.
        gap = [CLEAN] * (DEFAULT_MIN_CLEAN_RUN - 1)
        w = window([{SIG_LATENCY_TELL: 6.0}] * 5 + gap + [{SIG_LATENCY_TELL: 6.0}] * 5)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_clean_run_at_the_floor_is_an_off_phase(self):
        gap = [CLEAN] * DEFAULT_MIN_CLEAN_RUN
        w = window([{SIG_LATENCY_TELL: 6.0}] * 5 + gap + [{SIG_LATENCY_TELL: 6.0}] * 5)
        assert classify_node(w).attack_type == ATTACK_ONOFF

    def test_leading_and_trailing_clean_cycles_are_not_off_phases(self):
        # Delayed onset must not read as an off phase, or every delayed sybil
        # would be labelled on-off.
        w = window([CLEAN] * 20 + [{SIG_LATENCY_TELL: 6.0}] * 10 + [CLEAN] * 20)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_more_off_phases_raise_confidence(self):
        bad, good = [{SIG_LATENCY_TELL: 5.0}] * 5, [CLEAN] * 5
        one = classify_node(window(bad + good + bad))
        three = classify_node(window((bad + good) * 3 + bad))
        assert three.confidence > one.confidence


class TestOnOffNeedsSustainedIntermittency:
    """Incidental quiet polls are not an on-off pattern.

    The case these pin, from the project's live testbed: a steady sybil,
    flagged on 198 of 250 cycles, whose clean runs were nearly all a single
    poll of jitter -- except two that happened to reach exactly
    DEFAULT_MIN_CLEAN_RUN. What separates it from a genuine on-off attacker is
    how much of the active span is quiet: 2.4% against 64%.
    """

    BAD = {SIG_LATENCY_TELL: 6.0}

    def test_steady_liar_with_two_incidental_gaps_stays_sybil(self):
        gap = [CLEAN] * DEFAULT_MIN_CLEAN_RUN
        w = window([self.BAD] * 60 + gap + [self.BAD] * 60 + gap + [self.BAD] * 60)
        result = classify_node(w)
        assert result.attack_type == ATTACK_SYBIL
        assert "sustained misreporting" in result.rationale

    def test_genuinely_intermittent_attacker_is_still_onoff(self):
        # The same two gaps, but now they are most of the span.
        bad, good = [self.BAD] * 4, [CLEAN] * 8
        result = classify_node(window(bad + good + bad + good + bad))
        assert result.attack_type == ATTACK_ONOFF
        assert "sustained intermittency" in result.rationale

    def test_many_sub_floor_gaps_cannot_accumulate_to_the_bar(self):
        # Gaps shorter than min_clean_run are the detector's own drain time, so
        # they must not count toward quiet time any more than they count as
        # off phases.
        jitter = [self.BAD] + [CLEAN] * (DEFAULT_MIN_CLEAN_RUN - 1)
        w = window(jitter * 40 + [self.BAD])
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_the_boundary_is_the_documented_fraction(self):
        # 3 clean cycles inside a 13-cycle span = 23%, over the 20% bar;
        # 3 inside 21 = 14%, under it. Same gap, same off-phase count -- only
        # the share of the span differs, which is exactly the rule's claim.
        gap = [CLEAN] * DEFAULT_MIN_CLEAN_RUN
        over = window([self.BAD] * 5 + gap + [self.BAD] * 5)
        under = window([self.BAD] * 9 + gap + [self.BAD] * 9)
        assert classify_node(over).attack_type == ATTACK_ONOFF
        assert classify_node(under).attack_type == ATTACK_SYBIL
        # If the constant moves, these spans stop testing the boundary.
        assert DEFAULT_MIN_QUIET_FRACTION == 0.20


class TestBlackholeVsGrayhole:
    def test_total_drop_is_blackhole(self):
        w = window([{SIG_PACKET_DROP: 1.0}] * 20)
        assert classify_node(w).attack_type == ATTACK_BLACKHOLE

    def test_partial_drop_is_grayhole(self):
        w = window([{SIG_PACKET_DROP: 0.55}] * 20)
        assert classify_node(w).attack_type == ATTACK_GRAYHOLE

    def test_boundary_is_the_documented_threshold(self):
        just_under = window([{SIG_PACKET_DROP: DEFAULT_BLACKHOLE_MIN_RATE - 0.01}] * 9)
        just_over = window([{SIG_PACKET_DROP: DEFAULT_BLACKHOLE_MIN_RATE}] * 9)
        assert classify_node(just_under).attack_type == ATTACK_GRAYHOLE
        assert classify_node(just_over).attack_type == ATTACK_BLACKHOLE

    def test_median_not_max_so_one_unlucky_sample_cannot_relabel(self):
        # A grayhole's timeout rate WILL touch 1.0 occasionally. A max-based
        # rule would call this a blackhole; the median must not.
        rates = [0.5] * 18 + [1.0, 1.0]
        w = window([{SIG_PACKET_DROP: r} for r in rates])
        assert classify_node(w).attack_type == ATTACK_GRAYHOLE

    def test_marginal_calls_report_lower_confidence(self):
        clear = classify_node(window([{SIG_PACKET_DROP: 1.0}] * 10))
        marginal = classify_node(
            window([{SIG_PACKET_DROP: DEFAULT_BLACKHOLE_MIN_RATE + 0.005}] * 10)
        )
        assert clear.confidence > marginal.confidence


class TestTrustRailEvidence:
    """The trust rail establishes the drop FAMILY and never the magnitude.

    On the live testbed a blackhole was quarantined on the trust rail with no
    flagged cycle at all, so the classifier abstained on a perfectly contained
    attack. SIG_TRUST_COLLAPSE is how the label gets to exist.
    """

    def test_trust_collapse_alone_establishes_the_drop_family(self):
        result = classify_node(window([{SIG_TRUST_COLLAPSE: 1.0}] * 10))
        assert result.attack_type == ATTACK_GRAYHOLE
        assert "magnitude is not" in result.rationale

    def test_it_reports_the_weaker_claim_when_the_magnitude_is_unmeasured(self):
        # Even at a 100% post-collapse failure rate the label stays grayhole,
        # because the rate is over a handful of trials and cannot carry the
        # split. The safe direction is understating the attack.
        result = classify_node(window([{SIG_TRUST_COLLAPSE: 1.0}] * 10))
        assert result.attack_type == ATTACK_GRAYHOLE
        assert result.confidence < 0.5

    def test_a_measured_rate_still_decides_the_magnitude(self):
        w = window([{SIG_PACKET_DROP: 1.0, SIG_TRUST_COLLAPSE: 1.0}] * 10)
        assert classify_node(w).attack_type == ATTACK_BLACKHOLE

    def test_trust_collapse_cannot_promote_a_grayhole_to_a_blackhole(self):
        """A blackhole fails everything, so it is isolated fastest, so it
        yields the fewest outcomes to characterise it. Only the measured rate
        may split the pair."""
        w = window([{SIG_PACKET_DROP: 0.55}] * 20 + [{SIG_TRUST_COLLAPSE: 1.0}] * 5)
        assert classify_node(w).attack_type == ATTACK_GRAYHOLE

    def test_it_does_not_dilute_the_lying_weighing(self):
        # The lying share is measured over family-bearing cycles, so extra
        # drop-side cycles cannot quietly push a real liar under the bar.
        w = window(
            [{SIG_LATENCY_TELL: 6.0}] * 12 + [{SIG_LATENCY_TELL: 6.0, SIG_TRUST_COLLAPSE: 1.0}] * 8
        )
        assert classify_node(w).attack_type == ATTACK_SYBIL


class TestSignalPrecedence:
    def test_lying_beats_dropping_because_a_slow_liar_also_times_out(self):
        # A CPU-burning sybil really is slow, so it raises the drop tell too.
        w = window([{SIG_LATENCY_TELL: 6.0, SIG_PACKET_DROP: 0.9}] * 20)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_a_minority_of_lying_cycles_cannot_outweigh_the_drops(self):
        # A handful of spurious lying cycles against dozens of true drops must
        # not turn a dropper into a sybil.
        w = window(
            [{SIG_PACKET_DROP: 0.55}] * 18 + [{SIG_PACKET_DROP: 0.55, SIG_CPU_HONESTY: 0.9}] * 2
        )
        result = classify_node(w)
        assert result.attack_type == ATTACK_GRAYHOLE
        assert "too thin to outweigh the drops" in result.rationale

    def test_the_boundary_is_the_documented_share(self):
        drop_only = {SIG_PACKET_DROP: 0.55}
        both = {SIG_PACKET_DROP: 0.55, SIG_CPU_HONESTY: 0.9}
        # Exactly at the share (6 of 24 family cycles): the lying family wins.
        assert classify_node(window([both] * 6 + [drop_only] * 18)).attack_type == ATTACK_SYBIL
        # One cycle under (5 of 24 = 0.21): it stays a dropper.
        under = window([both] * 5 + [drop_only] * 19)
        assert classify_node(under).attack_type == ATTACK_GRAYHOLE
        assert DEFAULT_MIN_LYING_SHARE == 0.25

    def test_a_liar_that_also_drops_is_not_demoted_to_a_dropper(self):
        """A true on-off attacker whose CPU burn genuinely times tasks out.

        It raised the drop tell on 30 cycles against 58 lying cycles. At a 0.50
        bar it came out `grayhole`; the weighing must not overcorrect.
        """
        w = window([{SIG_PACKET_DROP: 0.5}] * 30 + [{SIG_LATENCY_TELL: 6.0}] * 58)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_lying_with_no_drops_at_all_is_still_the_sybil_family(self):
        # p2c can starve a quarantined liar of traffic entirely, so "no drop
        # evidence" is a routine state, not an exonerating one.
        w = window([CLEAN] * 30 + [{SIG_CPU_HONESTY: 0.9}] * 2)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_unreachable_alone_is_a_liveness_failure_not_an_attack(self):
        assert classify_node(window([{SIG_UNREACHABLE: 1.0}] * 10)).attack_type == NODE_DOWN

    def test_a_node_that_lied_then_died_is_still_an_attacker(self):
        w = window([{SIG_LATENCY_TELL: 6.0}] * 10 + [{SIG_UNREACHABLE: 1.0}] * 10)
        assert classify_node(w).attack_type == ATTACK_SYBIL

    def test_blackhole_is_not_confused_with_node_down(self):
        # The blackhole answers /status perfectly well and drops only tasks.
        assert classify_node(window([{SIG_PACKET_DROP: 1.0}] * 10)).attack_type == ATTACK_BLACKHOLE


class TestClientClassification:
    def test_ip_pin_denial_is_spoof(self):
        result = classify_client(window([{SIG_AUTH_IP_PIN: 1.0}]))
        assert result.attack_type == ATTACK_SPOOF
        assert result.confidence == 1.0

    def test_bad_response_denial_is_bad_credentials(self):
        result = classify_client(window([{SIG_AUTH_BAD_RESPONSE: 1.0}]))
        assert result.attack_type == ATTACK_BAD_CREDENTIALS

    def test_flood_tell_is_flood(self):
        assert classify_client(window([{SIG_FLOOD: 40.0}] * 3)).attack_type == ATTACK_FLOOD

    def test_auth_verdicts_latch_but_flood_does_not(self):
        # A cryptographic denial is a discrete event that stays true; a request
        # rate is a condition that can stop holding.
        stale = 10_000.0
        assert classify_client(window([{SIG_AUTH_IP_PIN: 1.0}]), now=stale) is not None
        assert classify_client(window([{SIG_FLOOD: 40.0}] * 3), now=stale) is None

    def test_spoof_beats_flood_when_both_are_present(self):
        w = window([{SIG_FLOOD: 40.0}, {SIG_AUTH_IP_PIN: 1.0}])
        assert classify_client(w).attack_type == ATTACK_SPOOF

    def test_no_evidence_abstains(self):
        assert classify_client(window([CLEAN] * 5)) is None


class TestAttackEvidence:
    def test_records_clean_cycles_so_off_phases_stay_visible(self):
        ev = AttackEvidence()
        phases = [{SIG_LATENCY_TELL: 6.0}] * 5 + [{}] * 5 + [{SIG_LATENCY_TELL: 6.0}] * 5
        for t, signals in enumerate(phases):
            ev.record_node("srv1", float(t), signals)
        assert ev.classify_node("srv1", now=float(len(phases))).attack_type == ATTACK_ONOFF

    def test_window_is_bounded(self):
        ev = AttackEvidence(window_cycles=10)
        for i in range(100):
            ev.record_node("srv1", float(i), {})
        assert len(ev._nodes["srv1"]) == 10

    def test_unknown_subject_abstains(self):
        assert AttackEvidence().classify_node("nope") is None

    def test_node_and_client_namespaces_are_separate(self):
        # Merging them would let a flooding client be scored against the edge
        # node it overwhelmed.
        ev = AttackEvidence()
        ev.record_node("srv1", 0.0, {SIG_LATENCY_TELL: 6.0})
        ev.record_client("srv1", 0.0, {SIG_FLOOD: 40.0})
        assert ev.node_subjects() == ["srv1"]
        assert ev.client_subjects() == ["srv1"]
        assert ev.classify_node("srv1", now=1.0).attack_type == ATTACK_SYBIL
        assert ev.classify_client("srv1", now=1.0).attack_type == ATTACK_FLOOD


def test_onoff_floor_matches_the_leaky_bucket_drain_plus_min_clean_run():
    # The classifier cannot see an off phase shorter than the detector's own
    # reaction time. If either side changes, this fails rather than the two
    # drifting apart silently.
    assert ONOFF_MIN_GOOD_PHASE_S == (1 + DEFAULT_MIN_CLEAN_RUN) * 1.0


@pytest.mark.parametrize(
    ("label", "family"),
    [
        (ATTACK_SYBIL, "load-dishonesty"),
        (ATTACK_ONOFF, "load-dishonesty"),
        (ATTACK_BLACKHOLE, "dropping"),
        (ATTACK_GRAYHOLE, "dropping"),
        ("something-new", "something-new"),
    ],
)
def test_family_of(label, family):
    assert family_of(label) == family
