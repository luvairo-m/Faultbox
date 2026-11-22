from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from faultbox.engine.models import AssignedResponse, RequestContext
from faultbox.engine.runtime import ScenarioEngine
from faultbox.scenario.loader import load_scenario
from faultbox.scenario.models import ResponseStep, Route, RouteMatch, Scenario


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([ResponseStep(201, repeat=2)], [(1, 201)] * 4),
        (
            [ResponseStep(503), ResponseStep(500, repeat=2), ResponseStep(200, repeat=2)],
            [(1, 503), (2, 500), (2, 500), (3, 200), (3, 200), (3, 200)],
        ),
        ([ResponseStep(500, repeat=10**12), ResponseStep(200)], [(1, 500)] * 3),
    ],
    ids=["single-step", "several-steps", "large-repeat"],
)
def test_engine_assigns_steps_in_order(
    steps: list[ResponseStep], expected: list[tuple[int, int]]
) -> None:
    engine = ScenarioEngine(Scenario(routes=[Route("items", "GET", "/items", steps)]))
    request = RequestContext("GET", "/items")

    for step_number, status in expected:
        response = engine.next_response(request)
        assert response is not None
        assert (response.step_number, response.status) == (step_number, status)


def test_routes_advance_independently() -> None:
    scenario = Scenario(
        routes=[
            Route("read", "GET", "/items", [ResponseStep(503, repeat=2), ResponseStep(200)]),
            Route("write", "POST", "/items", [ResponseStep(500), ResponseStep(201)]),
        ]
    )
    engine = ScenarioEngine(scenario)
    read_request = RequestContext("GET", "/items")
    write_request = RequestContext("POST", "/items")
    requests = [read_request, write_request, read_request, read_request, write_request, read_request]

    assignments = []
    for request in requests:
        response = engine.next_response(request)
        assert response is not None
        assignments.append(
            (response.route_id, response.step_number, response.assignment_number, response.status)
        )

    assert assignments == [
        ("read", 1, 1, 503),
        ("write", 1, 1, 500),
        ("read", 1, 2, 503),
        ("read", 2, 3, 200),
        ("write", 2, 2, 201),
        ("read", 2, 4, 200),
    ]


def test_unknown_request_does_not_consume_a_step() -> None:
    scenario = Scenario(
        routes=[Route("items", "GET", "/items", [ResponseStep(200), ResponseStep(204)])]
    )
    engine = ScenarioEngine(scenario)

    assert engine.next_response(RequestContext("GET", "/missing")) is None
    assert engine.next_response(RequestContext("POST", "/items")) is None
    assert engine.next_response(RequestContext("GET", "/items")) == AssignedResponse(
        route_id="items",
        step_number=1,
        assignment_number=1,
        status=200,
        headers={},
        body="",
        delay_ms=0,
    )


def test_route_variants_keep_scenario_order() -> None:
    scenario = Scenario(
        routes=[
            Route(
                "specific",
                "GET",
                "/items",
                [ResponseStep(201)],
                match=RouteMatch(headers={"X-Mode": "special"}, query={"tag": "python"}),
            ),
            Route("fallback", "GET", "/items", [ResponseStep(200)]),
        ]
    )
    engine = ScenarioEngine(scenario)
    request = RequestContext(
        "GET", "/items", headers={"X-Mode": "special"}, query={"tag": ["python"]}
    )

    response = engine.next_response(request)

    assert response is not None
    assert (response.route_id, response.step_number, response.status) == ("specific", 1, 201)


def test_new_engine_starts_over_and_preserves_configuration() -> None:
    first_step = ResponseStep(503, headers={"Retry-After": "1"}, body="retry", delay_ms=150)
    scenario = Scenario(
        routes=[Route("items", "GET", "/items", [first_step, ResponseStep(200)])]
    )
    original = deepcopy(scenario)
    engine = ScenarioEngine(scenario)
    request = RequestContext("GET", "/items")

    expected = AssignedResponse(
        route_id="items",
        step_number=1,
        assignment_number=1,
        status=503,
        headers={"Retry-After": "1"},
        body="retry",
        delay_ms=150,
    )
    response = engine.next_response(request)

    assert response is not None
    assert response == expected
    response.headers["Retry-After"] = "2"
    restarted = ScenarioEngine(scenario).next_response(request)
    continued = engine.next_response(request)

    assert restarted == expected
    assert continued is not None
    assert (continued.step_number, continued.assignment_number, continued.status) == (2, 2, 200)
    assert scenario == original


def test_engine_uses_body_already_loaded_from_file(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        """
[[routes]]
id = "items"
method = "GET"
path = "/items"

[[routes.steps]]
status = 200
body_file = "response.txt"
""",
        encoding="utf-8",
    )
    body_path = tmp_path / "response.txt"
    body_path.write_text("ответ", encoding="utf-8")
    scenario = load_scenario(scenario_path)
    body_path.unlink()

    response = ScenarioEngine(scenario).next_response(RequestContext("GET", "/items"))

    assert response is not None
    assert response.body == "ответ"
