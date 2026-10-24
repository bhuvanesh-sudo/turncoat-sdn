"""``turncoat run --attack``, ``--onset`` and ``--identity-binding``; client rows in ``score``."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from turncoat_sdn.attacks import Blackhole, Grayhole, IdentitySpoof, OnOff, Sybil
from turncoat_sdn.cli.attack_spec import AttackSpec, AttackSpecError, parse_attack, place_attacks
from turncoat_sdn.cli.common import EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.cli.run import record_run
from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file
from turncoat_sdn.sim import SimConfig

CFG = SimConfig()
THIRTY_S = SimConfig(sim_s=30.0)
SHORT_SECONDS = "30"


class TestParse:
    @pytest.mark.parametrize(
        ("text", "spec"),
        [
            ("spoof", AttackSpec("spoof")),
            (
                "spoof,client=iot38,target=iot5,start=15",
                AttackSpec("spoof", client=37, target=4, start=15.0),
            ),
            ("sybil,node=srv3", AttackSpec("sybil", node=2)),
            ("grayhole, start = 20", AttackSpec("grayhole", start=20.0)),
            ("blackhole", AttackSpec("blackhole")),
            ("drop,start=0", AttackSpec("drop", start=0.0)),
            ("onoff,node=srv1", AttackSpec("onoff", node=0)),
        ],
    )
    def test_parses(self, text, spec):
        assert parse_attack(text) == spec

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("teleport", "unknown attack"),
            ("spoof,node=srv1", "takes client, target, start"),
            ("sybil,client=iot1", "takes node, start"),
            ("spoof,start", "not key=value"),
            ("spoof,start=", "not key=value"),
            ("spoof,start=soon", "not a number"),
            ("spoof,start=-1", "0 or more"),
            ("spoof,start=inf", "0 or more"),
            ("spoof,client=38", "device name like iot38"),
            ("spoof,client=iot0", "device name like iot38"),
            ("sybil,node=server3", "device name like srv3"),
            ("spoof,start=1,start=2", "given twice"),
        ],
    )
    def test_refuses(self, text, match):
        with pytest.raises(AttackSpecError, match=match):
            parse_attack(text)


class TestPlace:
    def test_adds_to_the_scenario(self):
        attacks, client_attacks = place_attacks([parse_attack("spoof")], "both", CFG)
        assert {i: type(a) for i, a in attacks.items()} == {7: Sybil, 6: Blackhole}
        ((j, spoof),) = client_attacks.items()
        assert (j, spoof.target, spoof.start_s) == (37, 0, 0.0)

    def test_server_attacks_take_the_highest_free_server(self):
        specs = [parse_attack("grayhole"), parse_attack("onoff")]
        attacks, _ = place_attacks(specs, "both", CFG)
        assert (type(attacks[5]), type(attacks[4])) == (Grayhole, OnOff)

    def test_built_from_the_config_like_the_scenario(self):
        cfg = replace(CFG, grayhole_drop_fraction=0.6, spoof_interval_s=3.0)
        attacks, client_attacks = place_attacks(
            [parse_attack("grayhole,node=srv2"), parse_attack("spoof")], "clean", cfg
        )
        assert attacks[1].drop_fraction == 0.6
        assert client_attacks[37].interval_s == 3.0

    def test_start_overrides_the_onset(self):
        cfg = replace(CFG, attack_start_s=10.0)
        attacks, client_attacks = place_attacks(
            [parse_attack("sybil,node=srv1"), parse_attack("spoof,start=25")], "sybil", cfg
        )
        assert (attacks[7].start_s, attacks[0].start_s, client_attacks[37].start_s) == (
            10.0,
            10.0,
            25.0,
        )

    def test_a_second_spoofer_picks_another_device(self):
        _, client_attacks = place_attacks([parse_attack("spoof")], "spoof", CFG)
        assert sorted(client_attacks) == [37, 39]
        assert all(isinstance(a, IdentitySpoof) for a in client_attacks.values())

    def test_the_default_spoofer_cannot_be_its_own_target(self):
        _, client_attacks = place_attacks([parse_attack("spoof,target=iot38")], "clean", CFG)
        ((j, spoof),) = client_attacks.items()
        assert (j, spoof.target) == (39, 37)

    @pytest.mark.parametrize(
        ("specs", "scenario", "match"),
        [
            (["sybil,node=srv8"], "sybil", "already runs sybil"),
            (["sybil,node=srv9"], "clean", "fleet of 8 servers"),
            (["spoof,client=iot38"], "spoof", "already runs spoof"),
            (["spoof,client=iot41"], "clean", "fleet of 40"),
            (["spoof,target=iot41"], "clean", "fleet of 40"),
            (["spoof,client=iot2,target=iot2"], "clean", "own identity"),
        ],
    )
    def test_refuses_what_cannot_be_placed(self, specs, scenario, match):
        with pytest.raises(AttackSpecError, match=match):
            place_attacks([parse_attack(s) for s in specs], scenario, CFG)

    def test_runs_out_of_servers(self):
        specs = [parse_attack("sybil")] * 9
        with pytest.raises(AttackSpecError, match="no server is free"):
            place_attacks(specs, "clean", CFG)


class TestRunCommand:
    def test_attack_reaches_the_recording(self, turncoat, tmp_path):
        path = tmp_path / "run.jsonl"
        code, out = turncoat(
            "run", "--scenario", "clean", "--attack", "spoof,start=10",
            "--duration", SHORT_SECONDS, "-o", str(path),
        )  # fmt: skip
        assert code == EXIT_OK
        assert "admission: 11 of 11 attacker requests refused" in out
        assert validate_file(path).ok
        nodes = read_events(path)[1]["graph"]["nodes"]
        assert [(n["id"], n["attack"]) for n in nodes if n["attack"] != "none"] == [
            ("iot38", "spoof")
        ]

    def test_onset_delays_the_scenarios_attackers(self, turncoat, tmp_path):
        path = tmp_path / "run.jsonl"
        code, _ = turncoat(
            "run", "--onset", "12", "--duration", SHORT_SECONDS, "-o", str(path), "-q"
        )
        assert code == EXIT_OK
        onsets = {
            n["id"]: n["attack_start_s"]
            for n in read_events(path)[1]["graph"]["nodes"]
            if "attack_start_s" in n
        }
        assert onsets == {"srv7": 12.0, "srv8": 12.0}

    def test_tofu_locks_out_the_real_device(self, turncoat, tmp_path):
        code, out = turncoat(
            "run", "--scenario", "spoof", "--identity-binding", "tofu",
            "--duration", SHORT_SECONDS, "-o", str(tmp_path / "run.jsonl"),
        )  # fmt: skip
        assert code == EXIT_OK
        assert "admission: 0 of 16 attacker requests refused;" in out
        assert "honest requests refused" in out

    def test_without_a_client_attacker_prints_no_admission_line(self, turncoat, tmp_path):
        _, out = turncoat("run", "--duration", "5", "-o", str(tmp_path / "r.jsonl"))
        assert "admission" not in out

    @pytest.mark.parametrize(
        "args",
        [
            ("--attack", "teleport"),
            ("--attack", "spoof,start=x"),
            ("--onset", "-1"),
            ("--onset", "soon"),
            ("--identity-binding", "trust_me"),
        ],
    )
    def test_bad_options_are_usage_errors(self, turncoat, args):
        code, _ = turncoat("run", *args)
        assert code == 2

    def test_an_attack_that_cannot_be_placed_exits_2(self, turncoat, tmp_path):
        code, out = turncoat(
            "run", "--scenario", "sybil", "--attack", "onoff,node=srv8",
            "-o", str(tmp_path / "r.jsonl"),
        )  # fmt: skip
        assert code == EXIT_UNREADABLE
        assert "srv8 already runs sybil" in out
        assert not (tmp_path / "r.jsonl").exists()


class TestScoreClients:
    def record(self, tmp_path, config=THIRTY_S):
        path = tmp_path / "spoof.jsonl"
        record_run(path, strategy="zt_sdn", scenario="spoof", seed=1, config=config)
        return path

    def test_spoofer_row_counts_its_refusals(self, tmp_path):
        scores = score_recording(read_events(self.record(tmp_path)))
        row = next(s for s in scores["subjects"] if s["subject"] == "iot38")
        assert (row["kind"], row["predicted"], row["refused_at_admission"]) == (
            "client",
            "spoof",
            16,
        )
        assert scores["detection"]["admission"] == {
            "refused": 16,
            "refused_attackers": 16,
            "refused_honest": 0,
        }

    def test_tofu_counts_the_victims_refusals_against_honest_devices(self, tmp_path):
        config = SimConfig(sim_s=30.0, identity_binding="tofu")
        scores = score_recording(read_events(self.record(tmp_path, config)))
        admission = scores["detection"]["admission"]
        assert admission["refused_attackers"] == 0
        assert admission["refused"] == admission["refused_honest"] > 0

    def test_summary_reports_admission(self, turncoat, tmp_path):
        code, out = turncoat("score", str(self.record(tmp_path)))
        assert code == EXIT_OK
        assert "iot38    spoof      named correctly as spoof" in out
        assert "16 requests refused at admission" in out
        assert "Admission: 16 requests refused, 16 from attackers and 0 from honest devices." in out

    def test_recordings_without_clients_keep_their_shape(self, tmp_path):
        path = tmp_path / "both.jsonl"
        record_run(path, strategy="zt_sdn", scenario="both", seed=1, config=SimConfig(sim_s=30))
        scores = json.loads(json.dumps(score_recording(read_events(path)), default=lambda _: None))
        assert "admission" not in scores["detection"]
        assert all("refused_at_admission" not in s for s in scores["subjects"])
