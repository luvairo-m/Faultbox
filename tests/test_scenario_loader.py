from pathlib import Path

import pytest

from faultbox.errors import ScenarioError
from faultbox.models import ResponseStep, RouteMatch
from faultbox.scenario_loader import load_scenario


def test_load_minimal_scenario(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.toml"
    scenario.write_text(
        """
[[routes]]
id = "payments"
method = "POST"
path = "/payments"

[[routes.steps]]
status = 500
repeat = 2

[[routes.steps]]
status = 200
""",
        encoding="utf-8",
    )

    (route,) = load_scenario(scenario).routes

    assert (route.id, route.method, route.path) == ("payments", "POST", "/payments")
    assert route.match == RouteMatch(headers={}, query={})
    assert [(step.status, step.repeat) for step in route.steps] == [(500, 2), (200, 1)]
    step = route.steps[1]
    assert (step.delay_ms, step.headers, step.body, step.body_file) == (0, {}, "", None)


def test_load_preserves_route_order_and_response_data(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.toml"
    scenario.write_text(
        """
[[routes]]
id = "specific"
method = "GET"
path = "/payments"
match.headers = { "X-Client" = "backend" }
match.query = { role = "admin" }

[[routes.steps]]
status = 200
body = '{"сообщение":'
headers = { "Content-Type" = "application/json" }
delay_ms = 100

[[routes]]
id = "fallback"
method = "GET"
path = "/payments"

[[routes.steps]]
status = 200
body_file = "responses/not-created.json"
""",
        encoding="utf-8",
    )

    routes = load_scenario(str(scenario)).routes

    assert [route.id for route in routes] == ["specific", "fallback"]
    assert routes[0].match == RouteMatch(
        headers={"X-Client": "backend"}, query={"role": "admin"}
    )
    assert routes[0].steps == [
        ResponseStep(
            status=200,
            body='{"сообщение":',
            headers={"Content-Type": "application/json"},
            delay_ms=100,
        )
    ]
    assert routes[1].steps[0].body_file == "responses/not-created.json"
    assert routes[1].steps[0].body is None


def test_load_reports_bad_toml(tmp_path: Path) -> None:
    scenario = tmp_path / "broken.toml"
    scenario.write_text("[[routes]", encoding="utf-8")

    with pytest.raises(ScenarioError, match=r"broken\.toml: invalid TOML"):
        load_scenario(scenario)


def test_load_reports_excessive_nesting(tmp_path: Path) -> None:
    scenario = tmp_path / "deep.toml"
    scenario.write_text("routes = " + "[" * 2000, encoding="utf-8")

    with pytest.raises(ScenarioError, match=r"deep\.toml: invalid TOML"):
        load_scenario(scenario)


def test_load_reports_invalid_utf8(tmp_path: Path) -> None:
    scenario = tmp_path / "invalid-utf8.toml"
    scenario.write_bytes(b"\xff")

    with pytest.raises(ScenarioError, match=r"invalid-utf8\.toml: scenario must be UTF-8"):
        load_scenario(scenario)


def test_load_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match=r"missing\.toml: cannot read scenario"):
        load_scenario(tmp_path / "missing.toml")


def test_load_reports_invalid_path(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="cannot read scenario"):
        load_scenario(tmp_path / "bad\0name.toml")


def test_load_reports_unsupported_method(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.toml"
    scenario.write_text(
        """
[[routes]]
id = "payments"
method = "PUT"
path = "/payments"

[[routes.steps]]
status = 200
""",
        encoding="utf-8",
    )

    with pytest.raises(ScenarioError, match=r"routes\[1\]\.method: expected GET or POST"):
        load_scenario(scenario)


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ("steps = 200", r"routes\[1\]\.steps: expected an array"),
        ("steps = [200]", r"routes\[1\]\.steps\[1\]: expected a table"),
        (
            "steps = [{ status = true }]",
            r"routes\[1\]\.steps\[1\]\.status: expected an integer",
        ),
        (
            'steps = [{ status = 200, body = "", body_file = "response.txt" }]',
            r"routes\[1\]\.steps\[1\]: body and body_file cannot be set together",
        ),
    ],
)
def test_load_reports_bad_structure(tmp_path: Path, steps: str, message: str) -> None:
    scenario = tmp_path / "structure.toml"
    scenario.write_text(
        '[[routes]]\nid = "payments"\nmethod = "POST"\npath = "/payments"\n' + steps,
        encoding="utf-8",
    )

    with pytest.raises(ScenarioError, match=message):
        load_scenario(scenario)
