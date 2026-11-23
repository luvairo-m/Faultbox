from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs

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


def test_response_sequences_and_counts_are_isolated_by_route_and_group() -> None:
    scenario = Scenario(
        routes=[
            Route(
                "priority",
                "GET",
                "/items",
                [ResponseStep(503, repeat=2), ResponseStep(200)],
                match=RouteMatch(query={"priority": "yes"}),
            ),
            Route("fallback", "GET", "/items", [ResponseStep(500), ResponseStep(204)]),
        ]
    )
    engine = ScenarioEngine(scenario)
    case_a = {"X-Test-Case-ID": "A"}
    case_b = {"X-Test-Case-ID": "B"}
    named_default = {"X-Test-Case-ID": "default"}
    priority = {"priority": ["yes"]}

    requests = [
        (case_a, priority, ("priority", 1, 503)),
        (case_b, priority, ("priority", 1, 503)),
        ({}, priority, ("priority", 1, 503)),
        (case_a, {}, ("fallback", 1, 500)),
        (case_b, {}, ("fallback", 1, 500)),
        (named_default, priority, ("priority", 1, 503)),
        ({}, {}, ("fallback", 1, 500)),
        ({"x-test-case-id": "\tA "}, priority, ("priority", 2, 503)),
        ({"X-Test-Case-ID": "a"}, priority, ("priority", 1, 503)),
        (case_b, priority, ("priority", 2, 503)),
        (case_a, priority, ("priority", 3, 200)),
        ({}, priority, ("priority", 2, 503)),
        (named_default, priority, ("priority", 2, 503)),
        ({}, {}, ("fallback", 2, 204)),
        (case_a, {}, ("fallback", 2, 204)),
        (case_a, priority, ("priority", 4, 200)),
    ]

    for headers, query, expected in requests:
        request = RequestContext("GET", "/items", headers, query)
        response = engine.next_response(request)

        assert response is not None, request
        assert (response.route_id, response.assignment_number, response.status) == expected, request


@pytest.mark.parametrize("blank_id", ["", " \t "], ids=["empty", "whitespace"])
def test_blank_test_case_id_uses_the_same_group_as_missing_header(blank_id: str) -> None:
    scenario = Scenario(
        routes=[Route("items", "GET", "/items", [ResponseStep(503), ResponseStep(200)])]
    )
    engine = ScenarioEngine(scenario)
    first = engine.next_response(RequestContext("GET", "/items"))
    second = engine.next_response(RequestContext("GET", "/items", {"X-Test-Case-ID": blank_id}))

    assert first is not None
    assert second is not None
    assert (first.assignment_number, first.status) == (1, 503)
    assert (second.assignment_number, second.status) == (2, 200)


def test_unknown_request_does_not_consume_a_step() -> None:
    scenario = Scenario(
        routes=[
            Route(
                "items",
                "GET",
                "/items",
                [ResponseStep(200), ResponseStep(204)],
                match=RouteMatch(
                    headers={"X-Client": "backend", "X-Mode": ""},
                    query={"tag": "python", "label": ""},
                ),
            )
        ]
    )
    engine = ScenarioEngine(scenario)
    headers = {"X-Client": "backend", "X-Mode": ""}
    query = {"tag": ["python"], "label": [""]}
    missing_header = RequestContext("GET", "/items", {"X-Client": "backend"}, query)
    missing_query = RequestContext("GET", "/items", headers, {"tag": ["python"]})

    assert engine.next_response(RequestContext("GET", "/items/", headers, query)) is None
    assert engine.next_response(RequestContext("POST", "/items", headers, query)) is None
    assert engine.next_response(missing_header) is None
    assert engine.next_response(missing_query) is None
    assert engine.next_response(RequestContext("GET", "/items", headers, query)) == AssignedResponse(
        route_id="items",
        step_number=1,
        assignment_number=1,
        status=200,
        headers={},
        body="",
        delay_ms=0,
    )


@pytest.mark.parametrize(
    ("headers", "query_string", "route_id", "status"),
    [
        ({"X-Client": "backend"}, "role=admin", "users-admin", 200),
        ({}, "role=guest", "users-guest", 200),
        ({}, "role=admin", "users-fallback", 400),
        ({}, "", "users-fallback", 400),
        (
            {"x-cLiEnT": "backend", "X-Test-Case-ID": "case-a"},
            "role=admin&extra=1",
            "users-admin",
            200,
        ),
        ({"X-Client": "Backend"}, "role=admin", "users-fallback", 400),
        ({"X-Client": "backend"}, "Role=admin", "users-fallback", 400),
        ({"X-Client": "backend"}, "role=Admin", "users-fallback", 400),
        ({"X-Client": "backend"}, "role=admin&role=guest", "users-guest", 200),
        ({"X-Client": "backend"}, "role=other&r%6Fle=%61dmin&role=other", "users-admin", 200),
    ],
)
def test_route_variants_match_in_scenario_order(
    headers: dict[str, str], query_string: str, route_id: str, status: int
) -> None:
    scenario = Scenario(
        routes=[
            Route(
                "users-guest",
                "GET",
                "/users",
                [ResponseStep(200)],
                match=RouteMatch(query={"role": "guest"}),
            ),
            Route(
                "users-admin",
                "GET",
                "/users",
                [ResponseStep(200)],
                match=RouteMatch(headers={"X-Client": "backend"}, query={"role": "admin"}),
            ),
            Route("users-fallback", "GET", "/users", [ResponseStep(400)]),
        ]
    )
    engine = ScenarioEngine(scenario)
    query = parse_qs(query_string, keep_blank_values=True)
    request = RequestContext("GET", "/users", headers, query)

    response = engine.next_response(request)

    assert response is not None
    assert (response.route_id, response.status) == (route_id, status)


@pytest.mark.parametrize("headers", [{}, {"X-Test-Case-ID": "A"}], ids=["shared", "named"])
def test_new_engine_starts_over_and_preserves_configuration(headers: dict[str, str]) -> None:
    first_step = ResponseStep(503, headers={"Retry-After": "1"}, body="retry", delay_ms=150)
    scenario = Scenario(
        routes=[Route("items", "GET", "/items", [first_step, ResponseStep(200)])]
    )
    original = deepcopy(scenario)
    engine = ScenarioEngine(scenario)
    request = RequestContext("GET", "/items", headers)

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
