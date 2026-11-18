"""Read and validate a TOML scenario before it is used by the server."""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

from faultbox.models import (
    DEFAULT_DELAY_MS,
    DEFAULT_REPEAT,
    SUPPORTED_METHODS,
    HttpMethod,
    ResponseStep,
    Route,
    RouteMatch,
    Scenario,
    ScenarioError,
)
from faultbox.validation.scenario_validation import validate_scenario
from faultbox.validation.toml_validation import (
    expect_array,
    expect_integer,
    expect_only_known_fields,
    expect_optional_string,
    expect_string,
    expect_string_table,
    expect_table,
)


def load_scenario(path: str | Path) -> Scenario:
    """Read and validate a scenario, including its response body files."""
    scenario_path = Path(path)

    try:
        scenario = _read_scenario(scenario_path)
        validate_scenario(scenario)
    except ValueError as error:
        raise ScenarioError(f"{scenario_path}: {error}") from error

    return scenario


def _read_scenario(path: Path) -> Scenario:
    document = _read_toml(path)

    expect_only_known_fields(document, {"routes"})

    raw_routes = expect_array(document.get("routes"), "routes")

    routes = [
        _parse_route(raw_route, f"routes[{route_number}]")
        for route_number, raw_route in enumerate(raw_routes, start=1)
    ]

    scenario = Scenario(routes=routes)

    _load_response_bodies(scenario, path.parent)

    return scenario


def _read_toml(path: Path) -> dict[str, object]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ScenarioError(f"{path}: cannot read scenario: {error.strerror}") from error
    except ValueError as error:
        raise ScenarioError(f"{str(path)!r}: cannot read scenario: {error}") from error

    try:
        return tomllib.loads(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ScenarioError(f"{path}: scenario must be UTF-8") from error
    except RecursionError as error:
        raise ScenarioError(f"{path}: invalid TOML: nesting is too deep") from error
    except ValueError as error:
        # TOMLDecodeError and errors converting oversized integers are ValueErrors.
        raise ScenarioError(f"{path}: invalid TOML: {error}") from error


def _parse_route(value: object, field: str) -> Route:
    route_table = expect_table(value, field)
    expect_only_known_fields(route_table, {"id", "method", "path", "steps", "match"}, field)

    route_id = expect_string(route_table.get("id"), f"{field}.id")
    method = _parse_method(route_table.get("method"), f"{field}.method")
    path = expect_string(route_table.get("path"), f"{field}.path")

    steps_field = f"{field}.steps"
    raw_steps = expect_array(route_table.get("steps"), steps_field)

    steps = [
        _parse_step(raw_step, f"{steps_field}[{step_number}]")
        for step_number, raw_step in enumerate(raw_steps, start=1)
    ]

    match = _parse_match(route_table.get("match", {}), f"{field}.match")

    return Route(id=route_id, method=method, path=path, steps=steps, match=match)


def _parse_method(value: object, field: str) -> HttpMethod:
    for method in SUPPORTED_METHODS:
        if value == method:
            return method

    allowed_methods = " or ".join(SUPPORTED_METHODS)

    raise ValueError(f"{field}: expected {allowed_methods}")


def _parse_step(value: object, field: str) -> ResponseStep:
    step_table = expect_table(value, field)
    allowed_fields = {"status", "headers", "body", "body_file", "delay_ms", "repeat"}

    expect_only_known_fields(step_table, allowed_fields, field)

    status = expect_integer(step_table.get("status"), f"{field}.status")
    delay_ms = expect_integer(step_table.get("delay_ms", DEFAULT_DELAY_MS), f"{field}.delay_ms")
    repeat = expect_integer(step_table.get("repeat", DEFAULT_REPEAT), f"{field}.repeat")
    headers = expect_string_table(step_table.get("headers", {}), f"{field}.headers")
    body = expect_optional_string(step_table.get("body"), f"{field}.body")
    body_file = expect_optional_string(step_table.get("body_file"), f"{field}.body_file")

    if body is not None and body_file is not None:
        raise ValueError(f"{field}: body and body_file cannot be set together")

    return ResponseStep(
        status=status,
        headers=headers,
        body=body,
        body_file=body_file,
        delay_ms=delay_ms,
        repeat=repeat,
    )


def _parse_match(value: object, field: str) -> RouteMatch:
    match_table = expect_table(value, field)
    expect_only_known_fields(match_table, {"headers", "query"}, field)

    headers = expect_string_table(match_table.get("headers", {}), f"{field}.headers")
    query = expect_string_table(match_table.get("query", {}), f"{field}.query")

    return RouteMatch(headers=headers, query=query)


def _load_response_bodies(scenario: Scenario, scenario_directory: Path) -> None:
    for route_number, route in enumerate(scenario.routes, start=1):
        for step_number, step in enumerate(route.steps, start=1):
            if step.body_file is None:
                continue

            field = f"routes[{route_number}].steps[{step_number}].body_file"
            step.body = _read_response_body(scenario_directory, step.body_file, field)


def _read_response_body(scenario_directory: Path, filename: str, field: str) -> str:
    path = Path(filename)

    if path.anchor:
        raise ValueError(f"{field}: expected a path relative to the scenario: {filename!r}")

    response_path = scenario_directory / path

    try:
        # Opening a device or a named pipe could block scenario loading.
        if not stat.S_ISREG(response_path.stat().st_mode):
            raise ValueError("expected a regular file")

        # Decode bytes directly to preserve the file's original line endings.
        return response_path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{field}: {filename!r} must be UTF-8") from error
    except OSError as error:
        raise ValueError(f"{field}: cannot read {filename!r}: {error.strerror}") from error
    except ValueError as error:
        raise ValueError(f"{field}: cannot read {filename!r}: {error}") from error
