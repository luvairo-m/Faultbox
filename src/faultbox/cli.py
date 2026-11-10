"""Command-line entry point for Faultbox."""

import argparse


def main() -> None:
    """Show the CLI help and reject unsupported arguments."""
    parser = argparse.ArgumentParser(
        prog="faultbox",
        description="Simulate external HTTP APIs using TOML scenarios.",
        epilog="Only help is available in this version.",
    )
    parser.parse_args()
    parser.print_help()
