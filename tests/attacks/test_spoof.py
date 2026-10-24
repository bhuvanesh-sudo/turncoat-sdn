"""Identity spoof: the client interface, the admission check, the simulator and the scorer.

An IoT device that holds the fleet key claims another device's identity from
its own address. These pin that the client attack interface keeps a device
quiet until its onset, that the admission check refuses the claim under the
provisioned roster whenever it comes, that trust on first use refuses it only
once the real device has spoken (and otherwise hands the identity to the
spoofer, as in the final-year project's live run 9), that a refused spoof
costs the fleet nothing, that runs without a client attacker are unchanged,
and that the attack scorer names the spoofer ``spoof``.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from turncoat_sdn.attacks import ClientAttack, IdentitySpoof, Sybil
from turncoat_sdn.cli.routers import STRATEGIES
from turncoat_sdn.events import EventWriter, read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.scoring.attack_report import score_run
from turncoat_sdn.sim import (
    SCENARIOS,
    IdentityBinding,
    SimConfig,
    client_id,
    client_ip,
    malicious_roles,
    scenario_attacks,
    scenario_client_attacks,
)
from turncoat_sdn.sim import simulate as _simulate
from turncoat_sdn.trust import SimTrustModel, latency_tell

SHORT = SimConfig(sim_s=40.0)
ONSET = 15.0
DELAYED = replace(SHORT, attack_start_s=ONSET)
TOFU = replace(SHORT, identity_binding="tofu")
HOOKS = {"trust": SimTrustModel, "latency_tell": latency_tell}
ZT_SDN = STRATEGIES["zt_sdn"]
SPOOFER, VICTIM = "iot38", "iot1"


def simulate(scenario="spoof", seed=3, config=SHORT, **kwargs):
    return _simulate(ZT_SDN, scenario, seed, config=config, name="zt_sdn", **HOOKS, **kwargs)


def record(tmp_path, scenario="spoof", seed=3, config=SHORT, name="run.jsonl", **kwargs):
    path = tmp_path / name
    with EventWriter(path, backend="sim", seed=seed, strategy="zt_sdn", scenario=scenario) as rec:
        run = simulate(scenario, seed, config, recorder=rec, **kwargs)
    return run, read_events(path), path


def of_type(events, kind):
    return [ev for ev in events if ev["type"] == kind]


def beat(config, start=0.0, interval=2.0):
    """How many requests a spoofer on a fixed beat sends from ``start`` to the end."""
    return int((config.sim_s - start) // interval) + 1


class TestClientInterface:
    def test_needs_a_name(self):
        class Nameless(ClientAttack):
            pass

        with pytest.raises(TypeError, match="name"):
            Nameless()

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "5", None])
    def test_rejects_a_bad_onset(self, bad):
        with pytest.raises(ValueError, match="start_s"):
            IdentitySpoof(start_s=bad)

    def test_default_sends_one_request_as_itself(self):
        class Once(ClientAttack):
            name = "once"

        attack = Once(start_s=5.0)
        assert attack.first_request_s() == 5.0
        assert attack.next_request_s(5.0, random.Random(0)) is None
        assert attack.identity(own=4, now=6.0) == 4

    def test_a_bad_interval_is_caught(self):
        class Stuck(ClientAttack):
            name = "stuck"

            def interval(self, now, rng):
                return 0.0

        with pytest.raises(ValueError, match="seconds > 0"):
            Stuck().next_request_s(1.0, random.Random(0))


class TestProfile:
    def test_label_and_defaults(self):
        attack = IdentitySpoof()
        assert attack.name == "spoof"
        assert (attack.start_s, attack.target, attack.interval_s) == (0.0, 0, 2.0)
        assert attack.ground_truth() == {"attack": "spoof", "attack_start_s": 0.0}

    def test_claims_the_target_only_after_the_onset(self):
        attack = IdentitySpoof(start_s=ONSET, target=4)
        assert attack.identity(own=37, now=ONSET - 0.1) == 37
        assert attack.identity(own=37, now=ONSET) == 4

    def test_sends_on_a_fixed_beat_without_drawing(self):
        attack = IdentitySpoof(start_s=3.0, interval_s=2.5)
        rng = random.Random(0)
        state = rng.getstate()
        assert attack.first_request_s() == 3.0
        assert attack.next_request_s(3.0, rng) == 5.5
        assert rng.getstate() == state

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "1", None])
    def test_rejects_a_bad_target(self, bad):
        with pytest.raises(ValueError, match="target"):
            IdentitySpoof(target=bad)

    @pytest.mark.parametrize("bad", [0, -2.0, float("inf"), "2"])
    def test_rejects_a_bad_interval(self, bad):
        with pytest.raises(ValueError, match="interval_s"):
            IdentitySpoof(interval_s=bad)


class TestAdmission:
    def test_addresses_follow_the_project(self):
        assert (client_id(0), client_ip(0)) == ("iot1", "10.0.0.1")
        assert (client_id(37), client_ip(37)) == ("iot38", "10.0.0.38")

    def test_roster_refuses_a_claim_from_the_wrong_address_whenever_it_comes(self):
        binding = IdentityBinding("roster", {"iot1": "10.0.0.1"})
        assert binding.admit("iot1", "10.0.0.38") == "ip_pin"  # before iot1 has spoken
        assert binding.admit("iot1", "10.0.0.1") is None
        assert binding.admit("iot1", "10.0.0.38") == "ip_pin"

    def test_roster_falls_back_to_first_use_for_an_unknown_device(self):
        binding = IdentityBinding("roster", {"iot1": "10.0.0.1"})
        assert binding.admit("iot99", "10.0.0.7") is None
        assert binding.admit("iot99", "10.0.0.8") == "ip_pin"

    def test_tofu_gives_the_identity_to_the_first_claim(self):
        binding = IdentityBinding("tofu", {"iot1": "10.0.0.1"})
        assert binding.admit("iot1", "10.0.0.38") is None  # the spoofer got there first
        assert binding.owner("iot1") == "10.0.0.38"
        assert binding.admit("iot1", "10.0.0.1") == "ip_pin"  # the real device is locked out

    def test_unknown_rule(self):
        with pytest.raises(ValueError, match="identity binding"):
            IdentityBinding("trust_me")


class TestScenario:
    def test_is_a_built_in_scenario(self):
        assert SCENARIOS[-1] == "spoof"
        assert scenario_attacks("spoof") == {}
        assert malicious_roles("spoof", 8) == {}

    def test_places_iot38_against_iot1(self):
        (j, attack), *rest = scenario_client_attacks("spoof", DELAYED).items()
        assert not rest
        assert (j, attack.target, attack.start_s, attack.interval_s) == (37, 0, ONSET, 2.0)

    @pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s != "spoof"])
    def test_no_other_scenario_has_a_client_attacker(self, scenario):
        assert scenario_client_attacks(scenario) == {}

    def test_unknown_scenario(self):
        with pytest.raises(ValueError, match="unknown scenario"):
            scenario_client_attacks("nope")


class TestInTheSimulator:
    def test_roster_refuses_every_attempt(self):
        run = simulate(config=DELAYED)
        assert run.client_attack_requests == beat(DELAYED, ONSET)
        assert run.client_attack_refused == run.client_attack_requests
        assert run.honest_refused == 0

    def test_a_refused_spoof_costs_the_fleet_nothing(self):
        clean, spoof = simulate("clean"), simulate("spoof")
        for field in ("offered", "completed", "failed", "latencies_ms", "served"):
            assert getattr(spoof, field) == getattr(clean, field), field

    def test_tofu_refuses_it_once_the_victim_has_spoken(self):
        run = simulate(config=replace(TOFU, attack_start_s=ONSET))
        assert run.client_attack_refused == run.client_attack_requests > 0
        assert run.honest_refused == 0

    def test_tofu_hands_the_identity_to_a_spoofer_that_claims_first(self):
        # Live run 9: the spoofer claims iot1 before iot1's first request, so
        # every spoofed request is admitted and the real iot1 is locked out.
        run = simulate(config=TOFU)
        assert run.client_attack_refused == 0
        assert run.client_attack_requests == beat(TOFU)
        assert run.honest_refused > 0

    def test_nothing_happens_before_the_onset(self, tmp_path):
        _, events, _ = record(tmp_path, config=DELAYED)
        denied = of_type(events, "auth_denied")
        assert denied
        assert min(ev["ts"] for ev in denied) == ONSET

    def test_the_spoofers_own_traffic_still_flows(self, tmp_path):
        _, events, _ = record(tmp_path, config=DELAYED)
        own = [ev for ev in of_type(events, "route") if ev["client_ip"] == client_ip(37)]
        assert any(ev["ts"] > ONSET for ev in own)

    def test_same_seed_same_file(self, tmp_path):
        _, _, a = record(tmp_path, name="a.jsonl")
        _, _, b = record(tmp_path, name="b.jsonl")
        assert a.read_bytes() == b.read_bytes()

    def test_client_attacks_replace_the_scenarios(self):
        run = simulate(client_attacks={5: IdentitySpoof(start_s=10.0, target=6)})
        assert run.client_attack_requests == beat(SHORT, 10.0)
        assert simulate(client_attacks={}).client_attack_requests == 0

    def test_mixes_with_server_attackers(self):
        run = simulate("both", client_attacks={37: IdentitySpoof()})
        assert run.time_to_isolate_s is not None
        assert run.client_attack_refused == run.client_attack_requests > 0

    @pytest.mark.parametrize(
        ("client_attacks", "error", "match"),
        [
            ({40: IdentitySpoof()}, ValueError, "client attack index"),
            ({-1: IdentitySpoof()}, ValueError, "client attack index"),
            ({3: Sybil()}, TypeError, "ClientAttack"),
            ({3: IdentitySpoof(target=3)}, ValueError, "own identity"),
            ({3: IdentitySpoof(target=40)}, ValueError, "spoof target"),
        ],
    )
    def test_bad_client_attacks_are_refused(self, client_attacks, error, match):
        with pytest.raises(error, match=match):
            simulate(client_attacks=client_attacks)

    def test_unknown_binding(self):
        with pytest.raises(ValueError, match="identity_binding"):
            simulate(config=replace(SHORT, identity_binding="nope"))


class TestRecording:
    def test_validates(self, tmp_path):
        _, _, path = record(tmp_path, config=DELAYED)
        report = validate_file(path)
        assert report.ok, report.format(str(path))

    def test_lists_the_devices_with_ground_truth(self, tmp_path):
        _, events, _ = record(tmp_path, config=DELAYED)
        devices = [n for n in events[1]["graph"]["nodes"] if n["kind"] == "iot"]
        assert len(devices) == SHORT.n_clients
        spoofer = next(d for d in devices if d["id"] == SPOOFER)
        assert spoofer == {
            "id": SPOOFER,
            "kind": "iot",
            "ip": "10.0.0.38",
            "attack": "spoof",
            "attack_start_s": ONSET,
        }
        assert all(d["attack"] == "none" for d in devices if d["id"] != SPOOFER)

    def test_refusals_carry_the_claim_and_the_real_sender(self, tmp_path):
        _, events, _ = record(tmp_path, config=DELAYED)
        assert {
            (ev["device_id"], ev["source_ip"], ev["kind"]) for ev in of_type(events, "auth_denied")
        } == {(VICTIM, "10.0.0.38", "ip_pin")}

    def test_runs_without_a_client_attacker_have_no_devices(self, tmp_path):
        _, events, _ = record(tmp_path, scenario="both")
        assert all(n["kind"] == "server" for n in events[1]["graph"]["nodes"])
        assert not of_type(events, "auth_denied")
        assert all("client_ip" not in ev for ev in of_type(events, "route"))


class TestScoring:
    @pytest.mark.parametrize("seed", [1, 2, 3, 1000])
    @pytest.mark.parametrize("config", [SHORT, DELAYED], ids=["at-start", "delayed"])
    def test_names_the_spoofer_at_its_first_attempt(self, tmp_path, seed, config):
        _, events, _ = record(tmp_path, seed=seed, config=config)
        results = {r.subject: r for r in score_run(events)}
        assert results[SPOOFER].predicted == "spoof"
        assert results[SPOOFER].detection_latency_s == 0.0
        assert [r.subject for r in results.values() if r.predicted != r.truth] == []

    def test_tofu_blames_the_victim_and_misses_the_spoofer(self, tmp_path):
        # A known limit, pinned: the refusals come from the real device's own
        # address, so the evidence points at it. See docs/attacks.md.
        _, events, _ = record(tmp_path, config=TOFU)
        results = {r.subject: r for r in score_run(events)}
        assert results[VICTIM].predicted == "spoof"
        assert results[SPOOFER].predicted == "none"
