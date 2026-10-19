"""Command-line entry point: ``turncoat``.

v0.1 ships only the entry point and ``--version`` so the console script can be
installed and tested from day one. The ``run``, ``score`` and ``validate``
commands land in v0.2 and ``compare`` in v0.4 (see docs/cli.md once written).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from turncoat_sdn import __version__

PROG = "turncoat"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Benchmark trust-aware SDN load balancers against delayed-onset (turncoat) attacks."
        ),
        epilog="Commands run, score, validate and compare arrive in later releases.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    # No subcommands exist yet (they arrive in v0.2), so show the help.
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
