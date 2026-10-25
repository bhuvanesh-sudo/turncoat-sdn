"""``examples/score_outside_recording.py``: a recording turncoat-sdn did not write, graded."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import read_events
from turncoat_sdn.events.validate import validate_file

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "score_outside_recording.py"


@pytest.fixture(scope="module")
def example():
    spec = importlib.util.spec_from_file_location("score_outside_recording", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recording(example, tmp_path):
    path = tmp_path / "outside.jsonl"
    example.outside_controller(str(path))
    return path


def test_the_outside_system_imports_nothing_from_turncoat_sdn():
    """Only grade() may use the package; the controller is plain standard library."""
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = {a.name for n in top_level if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in top_level if isinstance(n, ast.ImportFrom)}
    assert not any(m and m.startswith("turncoat_sdn") for m in modules)


def test_its_recording_is_valid_schema_1_0(recording):
    report = validate_file(recording)
    assert report.ok, report.format(str(recording))
    header = read_events(recording)[0]
    assert (header["schema_version"], header["backend"]) == ("1.0", "live")


def test_it_is_scored_against_its_own_ground_truth(recording, example):
    scores = score_recording(read_events(recording))
    (attacker,) = [s for s in scores["subjects"] if s["truth"] != "none"]
    assert (attacker["subject"], attacker["truth"], attacker["onset_s"]) == (
        "srv3",
        "blackhole",
        example.ONSET,
    )
    assert scores["detection"]["attackers_named"] == 1
    assert scores["detection"]["attackers_quarantined"] == 1
    assert scores["service"]["offered"] == int(example.RUN_S * example.RATE_HZ)


def test_the_same_inputs_give_the_same_file(example, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    example.outside_controller(str(a))
    example.outside_controller(str(b))
    assert a.read_bytes() == b.read_bytes()


def test_runs_as_a_script(tmp_path):
    path = tmp_path / "my_run.jsonl"
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "-o", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "valid, schema 1.0" in result.stdout
    assert "srv3     blackhole  named correctly as blackhole" in result.stdout
    assert "1 of 1 attackers named correctly" in result.stdout
    cli = subprocess.run(
        [sys.executable, "-m", "turncoat_sdn.cli", "score", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "named correctly as blackhole" in cli.stdout
