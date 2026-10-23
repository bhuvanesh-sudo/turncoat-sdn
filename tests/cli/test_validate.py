"""``turncoat validate``: the same verdicts as ``python -m turncoat_sdn.events.validate``."""

from __future__ import annotations

from pathlib import Path

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE

EVENTS = Path(__file__).parent.parent / "events"
SAMPLE = str(EVENTS / "sample_run.jsonl")
BROKEN = str(EVENTS / "broken_run.jsonl")


def test_valid_recording(turncoat):
    code, out = turncoat("validate", SAMPLE)
    assert code == EXIT_OK
    assert "valid, schema 1.0" in out


def test_broken_recording_lists_its_problems(turncoat):
    code, out = turncoat("validate", BROKEN)
    assert code == EXIT_FAILED
    assert "line " in out


def test_missing_file_exits_2(turncoat, tmp_path):
    code, out = turncoat("validate", str(tmp_path / "missing.jsonl"))
    assert code == EXIT_UNREADABLE
    assert "cannot read" in out


def test_worst_status_wins_across_files(turncoat, tmp_path):
    code, out = turncoat("validate", SAMPLE, BROKEN, str(tmp_path / "missing.jsonl"))
    assert code == EXIT_UNREADABLE
    assert out.count("\n") >= 3


def test_max_problems_trims_the_list(turncoat):
    code, out = turncoat("validate", BROKEN, "--max-problems", "1")
    assert code == EXIT_FAILED
    assert "more" in out


def test_needs_at_least_one_file(turncoat):
    code, _ = turncoat("validate")
    assert code == 2
