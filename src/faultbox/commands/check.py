"""Validate a scenario from the command line."""

from __future__ import annotations

import sys
from pathlib import Path

from faultbox.models import ScenarioError
from faultbox.scenario_loader import load_scenario


def check_scenario(path: Path) -> int:
    """Validate a scenario and report its result to the terminal."""
    try:
        load_scenario(path)
    except ScenarioError as error:
        print(f"faultbox: {error}", file=sys.stderr)
        return 1

    print(f"Scenario is valid: {path}")

    return 0
