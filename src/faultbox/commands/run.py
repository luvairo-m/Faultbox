"""Validate a scenario and run the local HTTP server."""

from __future__ import annotations

import errno
import sys
from pathlib import Path

from faultbox.engine.runtime import ScenarioEngine
from faultbox.scenario.loader import ScenarioError, load_scenario
from faultbox.scenario.models import Scenario
from faultbox.server import HOST, create_server


def run_scenario(path: Path, port: int) -> int:
    """Validate the scenario, then serve until interrupted."""
    try:
        scenario = _load_scenario_for_run(path)
    except ScenarioError as error:
        print(f"faultbox: {error}", file=sys.stderr)
        return 1

    return _serve_locally(port, ScenarioEngine(scenario))


def _load_scenario_for_run(path: Path) -> Scenario:
    scenario = load_scenario(path)

    for route in scenario.routes:
        if any(step.delay_ms > 0 for step in route.steps):
            raise ScenarioError(
                f"{path}: route {route.id!r}: delay_ms > 0 is not supported yet"
            )

    return scenario


def _serve_locally(port: int, engine: ScenarioEngine) -> int:
    try:
        server = create_server(port, engine)
    except OSError as error:
        detail = "port is already in use" if error.errno == errno.EADDRINUSE else str(error)
        print(f"faultbox: cannot listen on {HOST}:{port}: {detail}", file=sys.stderr)
        return 1

    try:
        with server:
            print(f"Listening on http://{HOST}:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass

    return 0
