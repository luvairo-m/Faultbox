"""Read a TOML scenario into the configuration models."""

import tomllib
from pathlib import Path

from faultbox.errors import ScenarioError
from faultbox.models import (
    DEFAULT_DELAY_MS,
    DEFAULT_REPEAT,
    SUPPORTED_METHODS,
    HttpMethod,
    ResponseStep,
    Route,
    RouteMatch,
    Scenario,
)
from faultbox.toml_fields import (
    expect_array,
    expect_integer,
    expect_optional_string,
    expect_string,
    expect_string_table,
    expect_table,
)


def load_scenario(path: str | Path) -> Scenario:
    """Read a scenario and check the structure needed by the models."""
    scenario_path = Path(path)
    document = _read_toml(scenario_path)

    try:
        raw_routes = expect_array(document.get("routes"), "routes")
        routes = [
            _parse_route(route, f"routes[{number}]")
            for number, route in enumerate(raw_routes, start=1)
        ]
    except ValueError as error:
        raise ScenarioError(f"{scenario_path}: {error}") from error

    return Scenario(routes=routes)


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
    route = expect_table(value, field)

    steps_field = f"{field}.steps"
    steps = expect_array(route.get("steps"), steps_field)

    match_field = f"{field}.match"
    match = expect_table(route.get("match", {}), match_field)

    return Route(
        id=expect_string(route.get("id"), f"{field}.id"),
        method=_method(route.get("method"), f"{field}.method"),
        path=expect_string(route.get("path"), f"{field}.path"),
        steps=[
            _parse_step(step, f"{steps_field}[{number}]")
            for number, step in enumerate(steps, start=1)
        ],
        match=RouteMatch(
            headers=expect_string_table(match.get("headers", {}), f"{match_field}.headers"),
            query=expect_string_table(match.get("query", {}), f"{match_field}.query"),
        ),
    )


def _parse_step(value: object, field: str) -> ResponseStep:
    step = expect_table(value, field)
    status = expect_integer(step.get("status"), f"{field}.status")
    headers = expect_string_table(step.get("headers", {}), f"{field}.headers")
    body = expect_optional_string(step.get("body"), f"{field}.body")
    body_file = expect_optional_string(step.get("body_file"), f"{field}.body_file")
    delay_ms = expect_integer(step.get("delay_ms", DEFAULT_DELAY_MS), f"{field}.delay_ms")
    repeat = expect_integer(step.get("repeat", DEFAULT_REPEAT), f"{field}.repeat")

    try:
        return ResponseStep(
            status=status,
            headers=headers,
            body=body,
            body_file=body_file,
            delay_ms=delay_ms,
            repeat=repeat,
        )
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def _method(value: object, field: str) -> HttpMethod:
    for method in SUPPORTED_METHODS:
        if value == method:
            return method

    allowed_methods = " or ".join(SUPPORTED_METHODS)

    raise ValueError(f"{field}: expected {allowed_methods}")
