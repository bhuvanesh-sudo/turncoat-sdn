"""Tests for the ``turncoat`` command-line entry point."""

from __future__ import annotations

import subprocess
import sys

import pytest

from turncoat_sdn import __version__
from turncoat_sdn.cli import PROG, main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"{PROG} {__version__}"


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_unknown_option_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--no-such-option"])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_module_is_runnable():
    result = subprocess.run(
        [sys.executable, "-m", "turncoat_sdn.cli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"{PROG} {__version__}"


def test_help_lists_all_commands(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    for command in ("run", "validate", "score", "replicate", "compare"):
        assert command in out


def test_module_runs_a_command(tmp_path):
    path = tmp_path / "run.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "turncoat_sdn.cli",
            "run",
            "--duration",
            "5",
            "-o",
            str(path),
            "-q",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
    assert path.exists()
