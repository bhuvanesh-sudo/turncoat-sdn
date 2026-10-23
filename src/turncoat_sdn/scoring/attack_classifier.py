"""Attack classification: detector signals in, one discrete attack label out.

Ported from the final-year project's ``controller/attack_classifier.py``. The
logic is unchanged; only internal notes were left behind.

The detectors answer "is this subject misbehaving?". This module answers
"which attack is it?", so a run can be scored with a real confusion matrix
rather than a list of quarantines.

It is deliberately a pure function over an evidence window (no I/O, no locks,
no controller state), for the same reason the latency tell is: the live
controller and the offline scorer (:mod:`turncoat_sdn.scoring.attack_report`)
must reach the *same* verdict from the same evidence, and the only way to
guarantee that is one implementation both call.

Why a WINDOW and not a single detection cycle
---------------------------------------------
Two pairs of attacks are not separable from one cycle's signals:

* blackhole vs. grayhole fire the *same* signal (the packet-drop timeout
  tell). They differ only in MAGNITUDE: a blackhole drops everything, a
  grayhole drops a fraction.
* sybil vs. on-off fire the *same* signals (the latency tell, and the CPU
  honesty check once load accumulates). They differ only in INTERMITTENCY: an
  on-off attacker goes genuinely, measurably honest between phases.

So a cycle's worth of signals is an :class:`Observation`, and classification
reads a sequence of them.

Abstention
----------
A window whose newest observation is stale returns None, and a window with no
flagged cycle at all returns None. Neither means "this subject is innocent".
It means "this classifier has no current opinion": a detector with no recent
evidence must abstain, not re-assert its last verdict. Deciding what an
abstention means for a score belongs to the scorer.

One exception: the auth-layer signals LATCH and the load/traffic signals do
not. "This device presented a correct response for another device's identity
at t=5" is a historical fact that stays true; "this node is currently slow
while claiming to be idle" is a condition that can stop being true.

node_down is not an attack
--------------------------
A node that stops answering ``/status`` is scored ``node_down``, never folded
into blackhole. The project's blackhole agent answers ``/status`` perfectly
well and drops only tasks, so silence on ``/status`` is a liveness failure.
Labelling a crashed node as an attacker would inflate exactly the detection
numbers this module exists to measure honestly.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

# --------------------------------------------------------------------------- #
# Signal keys. Emitted as a structured dict alongside (never instead of) any
# human-readable reasons -- classification must not depend on regexing
# sentences written to be read by people.
# --------------------------------------------------------------------------- #
SIG_CPU_HONESTY = "cpu_honesty"  # value: |claimed - reference| deviation
SIG_LATENCY_TELL = "latency_tell"  # value: measured RTT / fleet median
SIG_PACKET_DROP = "packet_drop"  # value: recent timeout rate, 0..1
SIG_UNREACHABLE = "unreachable"  # value: 1.0 (presence is the signal)
SIG_FLOOD = "flood"  # value: measured rate / expected rate
SIG_AUTH_IP_PIN = "auth_ip_pin"  # value: 1.0 -- correct key, wrong source
SIG_AUTH_BAD_RESPONSE = "auth_bad_response"  # value: 1.0 -- key not held
SIG_TRUST_COLLAPSE = "trust_collapse"  # value: post-collapse failure rate, 0..1

# Signals that say "this subject is lying about its own load". A pure dropper
# reports its CPU honestly and answers /status at fleet speed, so it never
# raises either of these -- which is what lets the drop family be told apart
# from the sybil family at all.
_LYING_SIGNALS = (SIG_CPU_HONESTY, SIG_LATENCY_TELL)
_AUTH_SIGNALS = (SIG_AUTH_IP_PIN, SIG_AUTH_BAD_RESPONSE)

#: Signals that say "this subject loses the work it is given". Both put a
#: subject in the drop family, but only SIG_PACKET_DROP carries a timeout rate
#: measured over enough samples to split blackhole from grayhole --
#: SIG_TRUST_COLLAPSE deliberately does not. See _split_drop_family.
_DROP_SIGNALS = (SIG_PACKET_DROP, SIG_TRUST_COLLAPSE)

# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #
ATTACK_SYBIL = "sybil"
ATTACK_BLACKHOLE = "blackhole"
ATTACK_GRAYHOLE = "grayhole"
ATTACK_ONOFF = "onoff"
ATTACK_FLOOD = "flood"
ATTACK_SPOOF = "spoof"
ATTACK_BAD_CREDENTIALS = "bad_credentials"
NODE_DOWN = "node_down"
NO_ATTACK = "none"

#: Every label the classifier can emit, plus NO_ATTACK for the scorer's benefit.
#: Ordered so a confusion matrix's axes come out in a stable, readable order.
ALL_LABELS = (
    ATTACK_SYBIL,
    ATTACK_BLACKHOLE,
    ATTACK_GRAYHOLE,
    ATTACK_ONOFF,
    ATTACK_FLOOD,
    ATTACK_SPOOF,
    ATTACK_BAD_CREDENTIALS,
    NODE_DOWN,
    NO_ATTACK,
)

#: Label -> family. Two attacks are separable from their sibling only by
#: MAGNITUDE (blackhole/grayhole) and two only by INTERMITTENCY (sybil/onoff),
#: and both distinctions need evidence the defence sometimes prevents from ever
#: accumulating -- see _split_drop_family and ONOFF_MIN_GOOD_PHASE_S. Scoring
#: the family alongside the exact label separates "the system had no idea"
#: from "the system knew what kind of attack this was but could not resolve
#: which of the pair".
ATTACK_FAMILIES = {
    ATTACK_SYBIL: "load-dishonesty",
    ATTACK_ONOFF: "load-dishonesty",
    ATTACK_BLACKHOLE: "dropping",
    ATTACK_GRAYHOLE: "dropping",
    ATTACK_FLOOD: "flooding",
    ATTACK_SPOOF: "identity",
    ATTACK_BAD_CREDENTIALS: "identity",
    NODE_DOWN: "liveness",
    NO_ATTACK: "none",
}


def family_of(label: str) -> str:
    """The family a label belongs to; unknown labels are their own family."""
    return ATTACK_FAMILIES.get(label, label)


#: Ground-truth ``attack`` strings, as written in a recording's ``topology``
#: event, mapped to this module's labels. ``drop`` is what the simulator and
#: the project's node agent call the always-drop attacker; ``blackhole`` is the
#: standard name, so reports speak in it.
GROUND_TRUTH_ALIASES = {
    "drop": ATTACK_BLACKHOLE,
    "blackhole": ATTACK_BLACKHOLE,
    "sybil": ATTACK_SYBIL,
    "grayhole": ATTACK_GRAYHOLE,
    "onoff": ATTACK_ONOFF,
    "flood": ATTACK_FLOOD,
    "spoof": ATTACK_SPOOF,
    "bad_credentials": ATTACK_BAD_CREDENTIALS,
    "none": NO_ATTACK,
}

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
#: Median timeout rate at or above which a dropper is called a blackhole rather
#: than a grayhole. The MEDIAN over flagged cycles, not the max: a grayhole's
#: rate is a binomial sample over a short rolling window (10 outcomes), so
#: given enough cycles it WILL touch 1.0 by chance and a max-based rule would
#: relabel it a blackhole on one unlucky draw.
DEFAULT_BLACKHOLE_MIN_RATE = 0.85

#: Consecutive clean cycles that count as a genuine "off" phase. The latency
#: tell's leaky bucket drains one strike per clean poll from a trip level of 3,
#: so a subject that has genuinely stopped misbehaving needs ~3 clean polls to
#: fall silent. Requiring 3 means ordinary single-poll jitter can never be read
#: as an off phase, so a steady sybil is not relabelled on-off by noise.
DEFAULT_MIN_CLEAN_RUN = 3

#: THE ON-OFF DETECTABILITY FLOOR -- a real limit, stated rather than hidden.
#:
#: Separating on-off from sybil requires actually OBSERVING a quiet stretch, so
#: the attacker's good phase has to outlast the detector's own reaction time.
#: After a bad->good switch the latency tell's bucket sits at persist+1 (4) and
#: drains one per poll, so it keeps flagging for ~1 more poll before going
#: quiet, and only then can min_clean_run clean polls accumulate:
#:
#:     good_phase_s  >~  (1 + DEFAULT_MIN_CLEAN_RUN) * poll_interval_s   ~= 4 s
#:
#: An attacker that toggles faster than that is still caught -- it trips the
#: same tells and is quarantined exactly like a sybil -- but it is *classified*
#: as sybil, because its intermittency is below the 1 Hz sampling resolution.
#: That is a sampling limit, not a bug: the label is wrong while the defence
#: is not.
ONOFF_MIN_GOOD_PHASE_S = (1 + DEFAULT_MIN_CLEAN_RUN) * 1.0

#: How old the newest observation may be before the classifier abstains, in
#: seconds.
DEFAULT_EVIDENCE_MAX_AGE_S = 15.0

#: Cycles retained per subject by AttackEvidence, and the scorer's default
#: replay window.
#:
#: This is the SECOND on-off resolution constraint. Naming an attacker on-off
#: requires the window to hold a bad phase, a full good phase, AND the
#: resumption after it. A window narrower than a whole on-off period mostly
#: contains one phase at a time, so it sees sustained misbehaviour and reports
#: sybil:
#:
#:     window_cycles  >~  2 * onoff_period_s / poll_interval_s
#:
#: 120 at a 1 Hz poll rate is two minutes, six periods of a 20 s on-off cycle.
DEFAULT_WINDOW_CYCLES = 120

#: Fraction of the subject's ACTIVE SPAN that must fall inside qualifying off
#: phases before the on-off label is used.
#:
#: Counting off phases is not enough: on the project's live testbed a steady
#: sybil, flagged on 198 of 250 cycles, still threw off two clean runs that
#: reached min_clean_run by chance. What separates the two is how much of the
#: span is actually quiet, and it is not a close call:
#:
#:     true sybil: 6 quiet cycles / 250 span    =  2.4%
#:     true onoff: ~145 quiet cycles / 227 span = 64%
#:
#: The threshold is derived rather than fitted. An on-off attacker with duty
#: cycle d is quiet for (1 - d) of its period, less the detector's own reaction
#: lag eaten off the front of every good phase:
#:
#:     quiet_fraction  ~=  (1 - d) - (1 + min_clean_run) / period_cycles
#:
#: At d = 0.5, a 20 s period and 1 Hz polling that is 0.5 - 0.2 = 0.30.
#: Setting the bar at 0.20 accepts attackers up to d ~= 0.6 while sitting an
#: order of magnitude above the incidental-gap case. A faster or busier on-off
#: attacker falls back to `sybil`: still caught, only the label loses
#: resolution.
DEFAULT_MIN_QUIET_FRACTION = 0.20

#: Share of a subject's family-bearing cycles that must carry a lying signal
#: before it is judged as a liar rather than as a dropper. See the weighing rule
#: in classify_node.
#:
#: The two directions are not symmetric:
#:   * "a pure dropper never raises a lying signal" -- FALSE: contaminated
#:     telemetry made droppers raise it on a minority of cycles.
#:   * "a liar that burns CPU also raises the drop tell" -- TRUE: its CPU burn
#:     genuinely times tasks out.
#: So the bar must be low enough to let a genuine liar through while it is
#: still accumulating evidence, and high enough that a few contaminated cycles
#: cannot flip a dropper. Swept against live recordings:
#:
#:     share | true on-off attacker | dropper with 0.10 lying contamination
#:      0.10 | onoff  ok            | sybil   -- WRONG, contamination wins
#:      0.15 | onoff  ok            | grayhole ok
#:      0.25 | onoff  ok            | grayhole ok      <- chosen, mid-band
#:      0.40 | onoff  ok            | grayhole ok
#:      0.50 | grayhole WRONG       | grayhole ok
#:
#: 0.25 sits ~0.15 clear on both sides: far above any plausible detector
#: false-positive rate and far below a real liar's share (0.67 to 0.95).
DEFAULT_MIN_LYING_SHARE = 0.25


class Observation(NamedTuple):
    """One detection cycle's evidence about one subject.

    An Observation with empty `signals` is a CLEAN CYCLE -- positive evidence
    that the subject was checked and found fine. That is not the same as no
    observation at all, and the on-off rule depends entirely on the difference:
    without recorded clean cycles there is no way to see an attacker go quiet.
    """

    t: float
    signals: Mapping[str, float]


@dataclass(frozen=True)
class Classification:
    """A verdict about one subject.

    confidence is an evidence-strength heuristic in [0, 1] -- more flagged
    cycles and a wider margin from the deciding threshold give a higher number.
    It is deliberately NOT presented as a calibrated probability, because
    nothing here was fitted to produce one; it exists to rank verdicts and to
    let a reader see which calls were marginal.
    """

    attack_type: str
    confidence: float
    rationale: str
    evidence_cycles: int
    first_flagged_t: float | None = None


def _flagged(window: Sequence[Observation]) -> list[Observation]:
    return [o for o in window if o.signals]


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


class OffPhases(NamedTuple):
    """How intermittent a subject's misbehaviour was, over its active span.

    `count` alone is not enough to call something on-off -- see
    DEFAULT_MIN_QUIET_FRACTION. `quiet_fraction` is what says whether the quiet
    is the subject's normal condition or a couple of stray polls.
    """

    count: int
    quiet_cycles: int
    span_cycles: int

    @property
    def quiet_fraction(self) -> float:
        return self.quiet_cycles / self.span_cycles if self.span_cycles else 0.0


def _measure_off_phases(
    window: Sequence[Observation],
    min_clean_run: int,
) -> OffPhases:
    """Measure the quiet stretches the subject took between misbehaving.

    Only the span from the first flagged cycle to the last is considered: clean
    cycles before a subject ever misbehaves are its honest pre-onset life, and
    clean cycles after the last flag are either recovery or the end of the
    recording. Neither is an "off phase" -- an off phase is bounded by
    misbehaviour on both sides, which is precisely the on-off signature and
    precisely what a steady sybil never produces.

    Gaps shorter than min_clean_run are NOT counted toward `quiet_cycles`
    either. They are the detector's own drain time and ordinary poll jitter.
    """
    indices = [i for i, o in enumerate(window) if o.signals]
    if len(indices) < 2:
        return OffPhases(0, 0, len(indices))

    count = 0
    quiet = 0
    for a, b in zip(indices, indices[1:], strict=False):
        gap = b - a - 1  # clean cycles strictly between two flagged ones
        if gap >= min_clean_run:
            count += 1
            quiet += gap
    return OffPhases(count, quiet, indices[-1] - indices[0] + 1)


def classify_node(
    window: Sequence[Observation],
    now: float | None = None,
    blackhole_min_rate: float = DEFAULT_BLACKHOLE_MIN_RATE,
    min_clean_run: int = DEFAULT_MIN_CLEAN_RUN,
    evidence_max_age_s: float = DEFAULT_EVIDENCE_MAX_AGE_S,
    min_quiet_fraction: float = DEFAULT_MIN_QUIET_FRACTION,
    min_lying_share: float = DEFAULT_MIN_LYING_SHARE,
) -> Classification | None:
    """Label an edge node from its recent detection cycles.

    Args:
        window: observations oldest-first, including clean cycles (see
            Observation -- the on-off rule cannot work without them).
        now: current time, for the staleness check. None skips the check, which
            is what the offline scorer wants when replaying a finished
            recording.

    Returns:
        A Classification, or None to abstain. None is never "innocent"; see the
        module docstring.
    """
    if not window:
        return None
    if now is not None and (now - window[-1].t) > evidence_max_age_s:
        # Stale evidence: abstain rather than re-assert the last verdict.
        return None

    flagged = _flagged(window)
    if not flagged:
        return None

    first_flagged_t = flagged[0].t
    n_flagged = len(flagged)

    lying = [o for o in flagged if any(s in o.signals for s in _LYING_SIGNALS)]
    dropping = [o for o in flagged if any(s in o.signals for s in _DROP_SIGNALS)]
    unreachable = [o for o in flagged if SIG_UNREACHABLE in o.signals]
    # Only the packet-drop tell's rate is a rate: it is measured over a minimum
    # number of outcomes. See _split_drop_family.
    rated = [float(o.signals[SIG_PACKET_DROP]) for o in flagged if SIG_PACKET_DROP in o.signals]
    # The weighing below is lying-vs-dropping, so it is measured over the cycles
    # that carry one of those two families and no others. An unreachable-only
    # cycle is evidence for neither and must not dilute either side.
    n_family = sum(
        1
        for o in flagged
        if any(s in o.signals for s in _LYING_SIGNALS) or any(s in o.signals for s in _DROP_SIGNALS)
    )

    # --- Liveness failure, checked first and never merged into an attack ---
    # Only when nothing else EVER fired in the window. A node that lied and
    # then died is still an attacker; a node that only ever went silent is a
    # node that went silent.
    if unreachable and not lying and not dropping:
        return Classification(
            attack_type=NODE_DOWN,
            confidence=min(1.0, len(unreachable) / 5.0),
            rationale=(
                f"/status unreachable on {len(unreachable)} of {len(window)} "
                f"cycles, with no honesty, latency or drop signal ever raised "
                f"-- liveness failure, not one of the modelled attacks"
            ),
            evidence_cycles=n_flagged,
            first_flagged_t=first_flagged_t,
        )

    # --- Sybil family: the subject lied about its own load -------------------
    # A CPU-burning liar genuinely does time tasks out too, so it raises both
    # families and must not be filed as a mere dropper. But a dropper with
    # contaminated telemetry can raise a lying signal on a few cycles, so the
    # lying signal is weighed, not given absolute precedence: it must carry at
    # least min_lying_share of the family-bearing cycles.
    lying_share = len(lying) / n_family if n_family else 0.0
    if lying and (lying_share >= min_lying_share or not dropping):
        off = _measure_off_phases(window, min_clean_run)
        # Intermittency has to be SUSTAINED to name the attack on-off, not just
        # present. See DEFAULT_MIN_QUIET_FRACTION.
        if off.quiet_fraction >= min_quiet_fraction:
            return Classification(
                attack_type=ATTACK_ONOFF,
                confidence=min(1.0, 0.5 + 0.25 * off.count),
                rationale=(
                    f"load-dishonesty signals on {len(lying)} cycle(s), "
                    f"interrupted by {off.count} clean run(s) of >= "
                    f"{min_clean_run} cycles accounting for "
                    f"{off.quiet_fraction:.0%} of its active span -- "
                    f"sustained intermittency, not steady misbehaviour"
                ),
                evidence_cycles=n_flagged,
                first_flagged_t=first_flagged_t,
            )
        return Classification(
            attack_type=ATTACK_SYBIL,
            confidence=min(1.0, len(lying) / 10.0),
            rationale=(
                f"load-dishonesty signals on {len(lying)} cycle(s), quiet for "
                f"only {off.quiet_fraction:.0%} of its active span across "
                f"{off.count} clean run(s) of >= {min_clean_run} cycles -- "
                f"sustained misreporting of its own load"
            ),
            evidence_cycles=n_flagged,
            first_flagged_t=first_flagged_t,
        )

    # --- Drop family: honest about load, loses the work ----------------------
    if dropping:
        contested = (
            ""
            if not lying
            else f", against load-dishonesty on only {len(lying)} of "
            f"{n_family} family cycle(s) ({lying_share:.0%}, under "
            f"{min_lying_share:.0%}) -- too thin to outweigh the drops"
        )
        label, confidence, why = _split_drop_family(
            dropping,
            rated,
            blackhole_min_rate,
        )
        return Classification(
            attack_type=label,
            confidence=confidence,
            rationale=why + contested + " -- loses the work it is given",
            evidence_cycles=n_flagged,
            first_flagged_t=first_flagged_t,
        )

    return None


def _split_drop_family(
    dropping: Sequence[Observation],
    rated: Sequence[float],
    blackhole_min_rate: float,
) -> tuple[str, float, str]:
    """Blackhole or grayhole -- and what to do when only one of those is knowable.

    Blackhole and grayhole differ only in MAGNITUDE, so splitting them needs a
    timeout RATE, and a rate needs samples. The packet-drop tell supplies one
    measured over a minimum number of outcomes. SIG_TRUST_COLLAPSE does not,
    and must not be allowed to pretend otherwise:

        A blackhole fails everything, so it is isolated fastest, so it yields
        the fewest outcomes to characterise it. Containment quality and
        magnitude evidence are in direct tension.

    So the trust rail establishes the FAMILY and is not consulted on the
    magnitude. With no rate available the call degrades to grayhole -- the
    weaker of the two claims, understating the attack rather than the system's
    knowledge of it. Confidence is floored to say the call is thin, and the
    rationale names the reason so no reader mistakes it for a measurement.
    """
    if not rated:
        return (
            ATTACK_GRAYHOLE,
            0.25,
            f"trust-rail isolation on {len(dropping)} cycle(s) with no "
            f"packet-drop tell to measure a timeout rate -- the drop family is "
            f"established but its magnitude is not, so this reports the weaker "
            f"of blackhole/grayhole",
        )

    median_rate = _median(rated)
    is_blackhole = median_rate >= blackhole_min_rate
    # Confidence falls off as the measured rate approaches the threshold from
    # either side -- a grayhole configured at 0.84 genuinely is a marginal call.
    margin = abs(median_rate - blackhole_min_rate)
    return (
        ATTACK_BLACKHOLE if is_blackhole else ATTACK_GRAYHOLE,
        min(1.0, 0.5 + margin * 2.0),
        f"packet-drop tell on {len(rated)} cycle(s), median timeout rate "
        f"{median_rate:.2f} {'>=' if is_blackhole else '<'} "
        f"{blackhole_min_rate:.2f}",
    )


def classify_client(
    window: Sequence[Observation],
    now: float | None = None,
    evidence_max_age_s: float = DEFAULT_EVIDENCE_MAX_AGE_S,
) -> Classification | None:
    """Label an IoT device/client from its recent evidence.

    A separate function from classify_node, not a mode of it, because the
    subject is a different kind of thing: the signals differ, and blaming an
    edge node for a client-side attack is a specific mistake to avoid.

    The auth signals LATCH and the flood signal does not -- see the module
    docstring for why that asymmetry is correct rather than convenient.
    """
    if not window:
        return None

    flagged = _flagged(window)
    if not flagged:
        return None

    first_flagged_t = flagged[0].t

    # Auth denials first, and exempt from the staleness check: a cryptographic
    # denial is a discrete event that happened, not a condition that might have
    # stopped holding. It also needs no persistence filter -- unlike every
    # statistical tell here, it cannot fire by chance.
    ip_pin = [o for o in flagged if SIG_AUTH_IP_PIN in o.signals]
    if ip_pin:
        return Classification(
            attack_type=ATTACK_SPOOF,
            confidence=1.0,
            rationale=(
                f"{len(ip_pin)} auth denial(s) for a device_id already pinned "
                f"to a different source IP -- a correct response from the wrong "
                f"host, which is possession of the fleet key without ownership "
                f"of the identity"
            ),
            evidence_cycles=len(flagged),
            first_flagged_t=first_flagged_t,
        )

    bad_key = [o for o in flagged if SIG_AUTH_BAD_RESPONSE in o.signals]
    if bad_key:
        return Classification(
            attack_type=ATTACK_BAD_CREDENTIALS,
            confidence=1.0,
            rationale=(
                f"{len(bad_key)} auth denial(s) on a wrong response -- the "
                f"device does not hold the fleet key and was refused at "
                f"admission, before any routing or trust logic saw it"
            ),
            evidence_cycles=len(flagged),
            first_flagged_t=first_flagged_t,
        )

    if now is not None and (now - window[-1].t) > evidence_max_age_s:
        return None

    flood = [o for o in flagged if SIG_FLOOD in o.signals]
    if flood:
        ratios = [float(o.signals[SIG_FLOOD]) for o in flood]
        peak = max(ratios)
        return Classification(
            attack_type=ATTACK_FLOOD,
            confidence=min(1.0, 0.5 + len(flood) / 10.0),
            rationale=(
                f"sustained request-rate tell on {len(flood)} sample(s), peak "
                f"{peak:.1f}x the configured per-device rate"
            ),
            evidence_cycles=len(flagged),
            first_flagged_t=first_flagged_t,
        )

    return None


#: Signature shared by classify_node and classify_client.
Classifier = Callable[..., Classification | None]


@dataclass
class AttackEvidence:
    """Bounded per-subject observation history for a live controller.

    The offline scorer builds its windows straight from the recording and does
    not need this; it exists so a controller can classify continuously without
    growing a list per node for the length of a run.
    """

    window_cycles: int = DEFAULT_WINDOW_CYCLES
    _nodes: dict[str, deque[Observation]] = field(default_factory=dict)
    _clients: dict[str, deque[Observation]] = field(default_factory=dict)

    def _bucket(self, store: dict[str, deque[Observation]], key: str) -> deque[Observation]:
        if key not in store:
            store[key] = deque(maxlen=self.window_cycles)
        return store[key]

    def record_node(self, node_id: str, t: float, signals: Mapping[str, float]) -> None:
        """Record one poll cycle for a node. Call this EVERY cycle, including
        clean ones -- passing an empty dict is how an off phase becomes
        visible, and the on-off rule cannot fire without it."""
        self._bucket(self._nodes, node_id).append(Observation(t, dict(signals)))

    def record_client(self, client: str, t: float, signals: Mapping[str, float]) -> None:
        self._bucket(self._clients, client).append(Observation(t, dict(signals)))

    def classify_node(self, node_id: str, now: float | None = None, **kwargs):
        return classify_node(list(self._nodes.get(node_id, ())), now=now, **kwargs)

    def classify_client(self, client: str, now: float | None = None, **kwargs):
        return classify_client(list(self._clients.get(client, ())), now=now, **kwargs)

    def node_subjects(self) -> list[str]:
        return list(self._nodes)

    def client_subjects(self) -> list[str]:
        return list(self._clients)
