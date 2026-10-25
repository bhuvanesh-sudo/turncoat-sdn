"""``turncoat convert``: bring a live recording into the shared format.

A front end to :func:`turncoat_sdn.events.convert_live_file`. It converts a
recording the final-year controller wrote on a live Mininet run, then
validates the result with the same checks as ``turncoat validate``, so the
next step is ``turncoat score``, exactly as for a simulated run.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

import argparse

from turncoat_sdn.cli.common import EXIT_FAILED, EXIT_OK, EXIT_UNREADABLE
from turncoat_sdn.events.live import ConversionError, convert_live_file
from turncoat_sdn.events.validate import validate_file


def add_parser(commands: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        "convert",
        help="convert a live recording from the final-year controller to the shared format",
        description=(
            "Convert an events.jsonl recording written by the final-year project's controller "
            "on a live run: add the header, count ts from the start of the run, put events in "
            "time order and drop the dashboard's seq counter. The result is validated, and "
            "scores with turncoat score like a simulated run."
        ),
        epilog="Exit status: 0 when converted and valid, 1 when the recording cannot be "
        "converted or the result is invalid, 2 when a file cannot be read or written.",
    )
    parser.add_argument("source", metavar="RECORDING", help="the live recording to convert")
    parser.add_argument(
        "-o", "--output", required=True, metavar="PATH", help="where to write the converted file"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="the run's seed, for the header (default none)"
    )
    parser.add_argument(
        "--strategy", default=None, help="the strategy the controller ran, for the header"
    )
    parser.add_argument("--scenario", default=None, help="the scenario name, for the header")
    parser.set_defaults(handler=handle)
    return parser


def handle(args: argparse.Namespace) -> int:
    try:
        conversion = convert_live_file(
            args.source,
            args.output,
            seed=args.seed,
            strategy=args.strategy,
            scenario=args.scenario,
        )
    except ConversionError as exc:
        print(f"{args.source}: cannot convert: {exc}")
        return EXIT_FAILED
    except (OSError, UnicodeDecodeError) as exc:
        print(f"turncoat convert: {getattr(exc, 'strerror', None) or exc}")
        return EXIT_UNREADABLE

    print(f"Converted {args.source} to {args.output}")
    for note in conversion.notes():
        print(f"  {note}")
    report = validate_file(args.output)
    print(report.format(args.output))
    if not report.ok:
        return EXIT_FAILED
    print(f"Next: turncoat score {args.output}")
    return EXIT_OK
