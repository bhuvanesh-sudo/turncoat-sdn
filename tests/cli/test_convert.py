"""``turncoat convert``: a live recording in, a valid one out, then ``score`` as usual."""

from __future__ import annotations

import json
from pathlib import Path

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.events import read_events

EVENTS = Path(__file__).parent.parent / "events"
FYP_LIVE = str(EVENTS / "fyp_live_run.jsonl")
SAMPLE = str(EVENTS / "sample_run.jsonl")


def test_converts_validates_and_says_what_next(turncoat, tmp_path):
    out = tmp_path / "live.jsonl"
    code, text = turncoat("convert", FYP_LIVE, "-o", str(out), "--strategy", "zt_sdn")
    assert code == EXIT_OK
    assert "out of time order" in text
    assert "valid, schema 1.0" in text
    assert f"Next: turncoat score {out}" in text
    header = read_events(out)[0]
    assert header["backend"] == "live"
    assert header["strategy"] == "zt_sdn"


def test_header_options(turncoat, tmp_path):
    out = tmp_path / "live.jsonl"
    code, _ = turncoat("convert", FYP_LIVE, "-o", str(out), "--seed", "4", "--scenario", "sybil")
    assert code == EXIT_OK
    header = read_events(out)[0]
    assert header["seed"] == 4
    assert header["scenario"] == "sybil"
    assert "strategy" not in header


def test_converted_recording_scores_like_a_simulated_one(turncoat, tmp_path):
    out = tmp_path / "live.jsonl"
    assert turncoat("convert", FYP_LIVE, "-o", str(out))[0] == EXIT_OK
    code, text = turncoat("score", str(out), "--json")
    assert code == EXIT_OK
    scores = json.loads(text)
    srv3 = next(s for s in scores["subjects"] if s["subject"] == "srv3")
    assert srv3["truth"] == "sybil"
    assert srv3["correct"]
    assert srv3["isolation_latency_s"] == 4.06
    assert scores["service"]["offered"] == 3


def test_the_raw_recording_does_not_score(turncoat):
    code, text = turncoat("score", FYP_LIVE)
    assert code == EXIT_FAILED
    assert "header" in text


def test_refuses_a_recording_already_in_the_format(turncoat, tmp_path):
    out = tmp_path / "live.jsonl"
    code, text = turncoat("convert", SAMPLE, "-o", str(out))
    assert code == EXIT_FAILED
    assert "cannot convert" in text
    assert "turncoat validate" in text
    assert not out.exists()


def test_invalid_result_exits_1_and_keeps_the_file(turncoat, tmp_path):
    source = tmp_path / "events.jsonl"
    topology = {"graph": {"nodes": [{"id": "srv1", "kind": "server", "attack": "none"}]}}
    lines = [
        {"type": "topology", "ts": 100.0, **topology},
        {"type": "route", "ts": 101.0, "chosen": "srv9"},
    ]
    source.write_text("".join(json.dumps(line) + "\n" for line in lines))
    out = tmp_path / "live.jsonl"
    code, text = turncoat("convert", str(source), "-o", str(out))
    assert code == EXIT_FAILED
    assert "not a server in the topology" in text
    assert out.exists()


def test_missing_file_exits_2(turncoat, tmp_path):
    code, text = turncoat("convert", str(tmp_path / "missing.jsonl"), "-o", str(tmp_path / "o"))
    assert code == EXIT_UNREADABLE
    assert "turncoat convert" in text


def test_needs_an_output(turncoat):
    code, _ = turncoat("convert", FYP_LIVE)
    assert code == 2
