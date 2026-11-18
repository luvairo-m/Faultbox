"""Command-line entry point for Faultbox."""

from __future__ import annotations

import argparse
from pathlib import Path

from faultbox.commands.check import check_scenario


def main() -> int:
    """Parse arguments and dispatch the selected command."""
    parser = argparse.ArgumentParser(
        prog="faultbox",
        description="Simulate external HTTP APIs using TOML scenarios.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser("check", help="Validate a TOML scenario.")
    check_parser.add_argument("scenario", type=Path, help="Path to the TOML scenario.")

    arguments = parser.parse_args()

    if arguments.command == "check":
        return check_scenario(arguments.scenario)

    parser.print_help()

    return 0
