"""Command-line entry point: ``turncoat``.

Owner: jv (Repo, CLI, tests and release track).

Three commands join the packages into one workflow::

    turncoat run --scenario both --strategy zt_sdn --seed 1 -o run.jsonl
    turncoat validate run.jsonl
    turncoat score run.jsonl

``run`` drives the simulator and records the run to ``events.jsonl``,
``validate`` checks a recording against the schema, and ``score`` grades it.
``compare`` arrives in v0.4. Every command and option is described in
docs/cli.md.

The CLI is the one place allowed to wire packages together (see
docs/architecture.md): it hands the simulator its router, trust model, latency
tell and recorder, and passes recordings to the scorers.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from turncoat_sdn import __version__
from turncoat_sdn.cli import run, score, validate
from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE

PROG = "turncoat"

__all__ = ["EXIT_FAILED", "EXIT_OK", "EXIT_UNREADABLE", "PROG", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with every subcommand attached."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Benchmark trust-aware SDN load balancers against delayed-onset (turncoat) attacks."
        ),
        epilog=(
            "Typical use: turncoat run -o run.jsonl, then turncoat score run.jsonl. "
            "Run 'turncoat <command> --help' for a command's options."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    run.add_parser(commands)
    validate.add_parser(commands)
    score.add_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    return args.handler(args)
