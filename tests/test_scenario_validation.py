from __future__ import annotations

import pytest

from faultbox.models import ResponseStep, Route, Scenario
from faultbox.validation.scenario_validation import validate_response_body, validate_scenario


@pytest.mark.parametrize(
    ("routes", "message"),
    [
        ([], "routes: expected a non-empty array"),
        (
            [Route(id="first", method="GET", path="/first", steps=[])],
            "routes[1].steps: expected a non-empty array",
        ),
    ],
    ids=["no-routes", "no-steps"],
)
def test_validate_scenario_requires_routes_and_steps(
    routes: list[Route], message: str
) -> None:
    with pytest.raises(ValueError) as error:
        validate_scenario(Scenario(routes=routes))

    assert str(error.value) == message


def test_validate_scenario_reports_invalid_step_in_memory() -> None:
    scenario = Scenario(
        routes=[
            Route(id="first", method="GET", path="/first", steps=[ResponseStep(status=200)]),
            Route(
                id="second",
                method="GET",
                path="/second",
                steps=[ResponseStep(status=200), ResponseStep(status=204, body="text")],
            ),
        ]
    )

    with pytest.raises(ValueError) as error:
        validate_scenario(scenario)

    assert str(error.value) == "routes[2].steps[2].body: status 204 requires an empty body"


@pytest.mark.parametrize(
    ("step", "field"),
    [
        (ResponseStep(status=True), "status"),
        (ResponseStep(status=200, delay_ms=False), "delay_ms"),
        (ResponseStep(status=200, repeat=True), "repeat"),
    ],
    ids=["status", "delay", "repeat"],
)
def test_validate_scenario_rejects_boolean_step_fields(
    step: ResponseStep, field: str
) -> None:
    route = Route(id="first", method="GET", path="/first", steps=[step])

    with pytest.raises(ValueError) as error:
        validate_scenario(Scenario(routes=[route]))

    assert str(error.value) == f"routes[1].steps[1].{field}: expected an integer"


def test_validate_response_body_reports_the_field_given_by_the_caller() -> None:
    with pytest.raises(ValueError) as error:
        validate_response_body(304, "text", "routes[1].steps[1].body_file")

    assert str(error.value) == (
        "routes[1].steps[1].body_file: status 304 requires an empty body"
    )
