"""Command-line entry point for Faultbox."""

from __future__ import annotations

import argparse
from pathlib import Path

from faultbox.commands.check import check_scenario
from faultbox.commands.run import run_scenario


def main() -> int:
    """Parse arguments and dispatch the selected command."""
    parser = _build_parser()
    arguments = parser.parse_args()

    if arguments.command == "check":
        return check_scenario(arguments.scenario)

    if arguments.command == "run":
        return run_scenario(arguments.scenario, arguments.port)

    parser.print_help()

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faultbox",
        description="Simulate external HTTP APIs using TOML scenarios.",
    )
    subparsers = parser.add_subparsers(dest="command")

    _configure_check_parser(subparsers.add_parser("check", help="Validate a TOML scenario."))
    _configure_run_parser(subparsers.add_parser("run", help="Start the local HTTP server."))

    return parser


def _configure_check_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("scenario", type=Path, help="Path to the TOML scenario.")


def _configure_run_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("scenario", type=Path, help="Path to the TOML scenario.")
    parser.add_argument(
        "--port", type=_parse_port, default=8080, help="Port (default: %(default)s)."
    )


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from error

    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")

    return port
