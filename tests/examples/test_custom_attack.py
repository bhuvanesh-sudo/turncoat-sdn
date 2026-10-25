"""``examples/custom_attack.py``: a new turncoat in under 50 lines, run as a user would."""

from __future__ import annotations

import ast
import importlib.util
import io
import random
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from turncoat_sdn.cli.score import score_recording
from turncoat_sdn.events import EventList, read_events
from turncoat_sdn.events.validate import validate_file

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "custom_attack.py"


@pytest.fixture(scope="module")
def example():
    spec = importlib.util.spec_from_file_location("custom_attack", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_lines(source: str) -> int:
    """Lines holding code: no blank lines, comments or docstrings."""
    docstrings: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and ast.get_docstring(
            node
        ):
            first = node.body[0]
            docstrings.update(range(first.lineno, first.end_lineno + 1))
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in skip and token.type != tokenize.ENDMARKER:
            lines.update(range(token.start[0], token.end[0] + 1))
    return len(lines - docstrings)


def test_under_50_lines_of_code():
    assert code_lines(EXAMPLE.read_text(encoding="utf-8")) < 50


def test_counter_ignores_docstrings_and_comments():
    source = (
        '"""Doc.\n\nMore."""\n\n'
        "# note\nx = 1  # trailing\n\n\n"
        'def f():\n    """Doc."""\n    return x\n'
    )
    assert code_lines(source) == 3


class TestSlowpoke:
    def test_honest_before_the_onset(self, example):
        attack = example.Slowpoke(start_s=30.0)
        assert attack.service_time(29.9, 0.2, random.Random(1)) == 0.2

    def test_slow_after_the_onset(self, example):
        attack = example.Slowpoke(start_s=30.0, slowdown=3.0)
        assert attack.service_time(30.0, 0.2, random.Random(1)) == pytest.approx(0.6)

    def test_ground_truth(self, example):
        assert example.Slowpoke(start_s=12.0).ground_truth() == {
            "attack": "slowpoke",
            "attack_start_s": 12.0,
        }

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_costs_slo_and_is_never_quarantined(self, example, seed):
        """The finding the example prints, seed by seed under zt_sdn."""
        scores = {}
        for label, attacks in (("honest", {}), ("slowpoke", example.SLOWPOKE)):
            recording = EventList(backend="sim", seed=seed, strategy="zt_sdn", scenario=label)
            example.run("zt_sdn", seed, attacks, recording)
            scores[label] = score_recording(recording.events)
        slow, honest = scores["slowpoke"], scores["honest"]
        assert slow["service"]["slo_violation_rate"] > honest["service"]["slo_violation_rate"]
        # It drops nothing: only the odd long task outlasts the client's timeout,
        # far too few for the timeout-rate tell.
        assert slow["service"]["failure_rate"] < 0.01
        assert slow["detection"]["attackers"] == 1
        assert slow["detection"]["attackers_quarantined"] == 0


def test_runs_as_a_script(tmp_path):
    recording = tmp_path / "slowpoke.jsonl"
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--seeds", "2", "--record", str(recording)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Slowpoke on srv8 from 30 s, 2 paired seeds" in result.stdout
    assert "zt_sdn" in result.stdout and "least_conn" in result.stdout
    assert "quarantined in 0 of 2 runs" in result.stdout
    assert validate_file(recording).ok
    (attacker,) = [
        s for s in score_recording(read_events(recording))["subjects"] if s["truth"] != "none"
    ]
    assert (attacker["subject"], attacker["truth"], attacker["onset_s"]) == (
        "srv8",
        "slowpoke",
        30.0,
    )
