"""``turncoat validate``: check recordings against the event schema.

A thin front end to :mod:`turncoat_sdn.events.validate`, so the checks and
messages are exactly the ones ``python -m turncoat_sdn.events.validate`` gives.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.events.validate import DEFAULT_MAX_PROBLEMS, validate_file


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} must be 1 or more")
    return value


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        "validate",
        help="check that recordings follow the events.jsonl schema",
        description=(
            "Check that one or more events.jsonl recordings follow the turncoat-sdn "
            "schema. Prints one verdict per file, listing every problem with its line."
        ),
        epilog="Exit status: 0 when every file is valid, 1 when any is not, 2 when one "
        "cannot be read.",
    )
    parser.add_argument("paths", nargs="+", metavar="RECORDING", help="JSONL recording(s)")
    parser.add_argument(
        "--max-problems",
        type=_positive_int,
        default=DEFAULT_MAX_PROBLEMS,
        metavar="N",
        help=f"problems to list per file before summarising (default {DEFAULT_MAX_PROBLEMS})",
    )
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    status = EXIT_OK
    for path in args.paths:
        try:
            report = validate_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot read: {getattr(exc, 'strerror', None) or exc}")
            status = max(status, EXIT_UNREADABLE)
            continue
        print(report.format(path, args.max_problems))
        if not report.ok:
            status = max(status, EXIT_FAILED)
    return status
