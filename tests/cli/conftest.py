"""Shared helpers for the CLI tests: run ``turncoat`` in-process and capture its output."""

from __future__ import annotations

import pytest

from turncoat_sdn.cli import main


@pytest.fixture
def turncoat(capsys):
    """``turncoat(*args) -> (exit_code, stdout)``, the way a shell would see it."""

    def call(*args: str) -> tuple[int, str]:
        try:
            code = main(list(args))
        except SystemExit as exc:  # argparse usage errors and --help
            code = exc.code if isinstance(exc.code, int) else 1
        return code, capsys.readouterr().out

    return call
