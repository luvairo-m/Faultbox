from pathlib import Path

import pytest

from faultbox.errors import ScenarioError
from faultbox.models import ResponseStep, RouteMatch
from faultbox.scenario_loader import load_scenario


_ROUTE_TOML = '[[routes]]\nid = "payments"\nmethod = "GET"\npath = "/payments"\n'
_STEP_TOML = "[[routes.steps]]\nstatus = 200\n"
_MATCH_TOML = (
    'match.headers = { "X-Client" = "backend", "X-Mode" = "test" }\n'
    'match.query = { role = "admin", page = "1" }\n'
)


def _write_scenario_file(tmp_path: Path, content: str) -> Path:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(content, encoding="utf-8")

    return scenario_path


def _assert_invalid_scenario(tmp_path: Path, content: str, message: str) -> None:
    scenario_path = _write_scenario_file(tmp_path, content)

    with pytest.raises(ScenarioError) as error:
        load_scenario(scenario_path)

    assert str(error.value).startswith(f"{scenario_path}: {message}")


def test_load_accepts_scenario_with_defaults(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
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

    (route,) = load_scenario(scenario_path).routes

    assert (route.id, route.method, route.path) == ("payments", "POST", "/payments")
    assert route.match == RouteMatch(headers={}, query={})
    assert [(step.status, step.repeat) for step in route.steps] == [(500, 2), (200, 1)]
    step = route.steps[1]
    assert (step.delay_ms, step.headers, step.body, step.body_file) == (0, {}, "", None)


def test_load_preserves_route_order_and_raw_response_body(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
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

    routes = load_scenario(str(scenario_path)).routes

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


def test_load_reports_invalid_toml(tmp_path: Path) -> None:
    scenario_path = tmp_path / "broken.toml"
    scenario_path.write_text("[[routes]", encoding="utf-8")

    with pytest.raises(ScenarioError, match=r"broken\.toml: invalid TOML"):
        load_scenario(scenario_path)


def test_load_reports_excessive_nesting(tmp_path: Path) -> None:
    scenario_path = tmp_path / "deep.toml"
    scenario_path.write_text("routes = " + "[" * 2000, encoding="utf-8")

    with pytest.raises(ScenarioError, match=r"deep\.toml: invalid TOML"):
        load_scenario(scenario_path)


def test_load_reports_invalid_utf8(tmp_path: Path) -> None:
    scenario_path = tmp_path / "invalid-utf8.toml"
    scenario_path.write_bytes(b"\xff")

    with pytest.raises(ScenarioError, match=r"invalid-utf8\.toml: scenario must be UTF-8"):
        load_scenario(scenario_path)


def test_load_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match=r"missing\.toml: cannot read scenario"):
        load_scenario(tmp_path / "missing.toml")


def test_load_reports_invalid_file_path(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="cannot read scenario"):
        load_scenario(tmp_path / "bad\0name.toml")


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("", "routes: expected an array"),
        ("routes = {}", "routes: expected an array"),
        ("routes = []", "routes: expected a non-empty array"),
        ("routes = [200]", "routes[1]: expected a table"),
        ("extra = true\n" + _ROUTE_TOML + _STEP_TOML, "extra: unknown field"),
        (
            r'"extra\nfield" = true' + "\n" + _ROUTE_TOML + _STEP_TOML,
            r"['extra\nfield']: unknown field",
        ),
        (
            _ROUTE_TOML + '"match.headers" = true\n' + _STEP_TOML,
            "routes[1]['match.headers']: unknown field",
        ),
        (_ROUTE_TOML, "routes[1].steps: expected an array"),
        (_ROUTE_TOML + "steps = 200", "routes[1].steps: expected an array"),
        (_ROUTE_TOML + "steps = []", "routes[1].steps: expected a non-empty array"),
        (_ROUTE_TOML + "steps = [200]", "routes[1].steps[1]: expected a table"),
    ],
)
def test_load_rejects_invalid_structure(tmp_path: Path, document: str, message: str) -> None:
    _assert_invalid_scenario(tmp_path, document, message)


@pytest.mark.parametrize(
    ("field_name", "value_toml", "message"),
    [
        ("id", None, "id: expected a string"),
        ("id", "42", "id: expected a string"),
        ("method", None, "method: expected GET or POST"),
        ("method", '"PUT"', "method: expected GET or POST"),
        ("method", '"get"', "method: expected GET or POST"),
        ("method", "true", "method: expected GET or POST"),
        ("path", None, "path: expected a string"),
        ("path", "[]", "path: expected a string"),
        ("path", '"payments"', "path: expected a path starting with '/'"),
        ("path", '"/payments?x=1"', "path: cannot contain a query or fragment"),
        ("path", '"/payments#fragment"', "path: cannot contain a query or fragment"),
        ("path", '"/payments today"', "path: cannot contain spaces or control characters"),
        ("path", r'"/payments\ttoday"', "path: cannot contain spaces or control characters"),
        ("path", r'"/payments\u0000"', "path: cannot contain spaces or control characters"),
        ("path", '"/__faultbox/reset"', "path: prefix /__faultbox/ is reserved"),
        ("extra", "true", "extra: unknown field"),
        ("match", "[]", "match: expected a table"),
        ("match.body", '"data"', "match.body: unknown field"),
        ("match.headers", "[]", "match.headers: expected a table"),
        ("match.query", "[]", "match.query: expected a table"),
        ("match.headers", '{ "X-Client" = 1 }', "match.headers['X-Client']: expected a string"),
        ("match.query", "{ role = true }", "match.query['role']: expected a string"),
        (
            "match.headers",
            '{ "X-Client" = "app", "x-client" = "app" }',
            "match.headers['x-client']: duplicate header name",
        ),
        (
            "match.headers",
            '{ "x-TEST-case-ID" = "case" }',
            "match.headers['x-TEST-case-ID']: header is reserved for test isolation",
        ),
    ],
)
def test_load_rejects_invalid_route_field(
    tmp_path: Path, field_name: str, value_toml: str | None, message: str
) -> None:
    fields = {"id": '"payments"', "method": '"GET"', "path": '"/payments"'}
    if value_toml is None:
        del fields[field_name]
    else:
        fields[field_name] = value_toml

    route_toml = "[[routes]]\n" + "".join(f"{key} = {literal}\n" for key, literal in fields.items())

    _assert_invalid_scenario(tmp_path, route_toml + _STEP_TOML, f"routes[1].{message}")


def test_load_rejects_duplicate_route_id_on_another_path(tmp_path: Path) -> None:
    first_route_toml = _ROUTE_TOML + _STEP_TOML
    second_route_toml = first_route_toml.replace('path = "/payments"', 'path = "/refunds"')

    _assert_invalid_scenario(
        tmp_path, first_route_toml + second_route_toml, "routes[2].id: duplicate route id 'payments'"
    )


@pytest.mark.parametrize(
    ("first_match_toml", "second_match_toml"),
    [
        ("", ""),
        ("", "match = { headers = {}, query = {} }\n"),
        (
            _MATCH_TOML,
            'match.headers = { "x-mode" = "test", "x-client" = "backend" }\n'
            'match.query = { page = "1", role = "admin" }\n',
        ),
    ],
)
def test_load_rejects_equivalent_route_variants(
    tmp_path: Path, first_match_toml: str, second_match_toml: str
) -> None:
    first_route_toml = _ROUTE_TOML + first_match_toml + _STEP_TOML
    second_route_toml = _ROUTE_TOML.replace('"payments"', '"other"') + second_match_toml + _STEP_TOML

    _assert_invalid_scenario(
        tmp_path,
        first_route_toml + second_route_toml,
        "routes[2].match: duplicate route variant for GET /payments",
    )


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('method = "GET"', 'method = "POST"'),
        ('path = "/payments"', 'path = "/payments/"'),
        ('path = "/payments"', 'path = "/payments%20today"'),
        ('"X-Client" = "backend"', '"x-client" = "Backend"'),
        ('role = "admin"', 'Role = "admin"'),
        ('role = "admin"', 'role = "Admin"'),
    ],
)
def test_load_accepts_distinct_route_variants(
    tmp_path: Path, original: str, replacement: str
) -> None:
    first_route_toml = _ROUTE_TOML + _MATCH_TOML + _STEP_TOML
    second_route_toml = first_route_toml.replace('"payments"', '"other"').replace(
        original, replacement
    )
    scenario_path = _write_scenario_file(tmp_path, first_route_toml + second_route_toml)

    assert [route.id for route in load_scenario(scenario_path).routes] == ["payments", "other"]


@pytest.mark.parametrize(
    ("step_fields_toml", "message"),
    [
        ("", ".status: expected an integer"),
        ("status = true", ".status: expected an integer"),
        ("status = 200.0", ".status: expected an integer"),
        ("status = 199", ".status: expected a status between 200 and 599"),
        ("status = 600", ".status: expected a status between 200 and 599"),
        ("status = 200\ndelay_ms = -1", ".delay_ms: expected an integer greater than or equal to 0"),
        ("status = 200\ndelay_ms = false", ".delay_ms: expected an integer"),
        ("status = 200\nrepeat = 0", ".repeat: expected an integer greater than or equal to 1"),
        ("status = 200\nrepeat = true", ".repeat: expected an integer"),
        ("status = 200\nextra = true", ".extra: unknown field"),
        ("status = 200\nbody = 42", ".body: expected a string"),
        ("status = 200\nbody_file = []", ".body_file: expected a string"),
        (
            'status = 200\nbody = ""\nbody_file = "response.txt"',
            ": body and body_file cannot be set together",
        ),
        ("status = 200\nheaders = true", ".headers: expected a table"),
        ("status = 200\nheaders = { X = 1 }", ".headers['X']: expected a string"),
    ],
)
def test_load_rejects_invalid_step_field(tmp_path: Path, step_fields_toml: str, message: str) -> None:
    document = _ROUTE_TOML + _STEP_TOML + "[[routes.steps]]\n" + step_fields_toml

    _assert_invalid_scenario(tmp_path, document, f"routes[1].steps[2]{message}")


@pytest.mark.parametrize("header_name", ["cOnTeNt-Length", "TRANSFER-encoding", "connection"])
def test_load_rejects_server_managed_response_header(tmp_path: Path, header_name: str) -> None:
    document = _ROUTE_TOML + _STEP_TOML + f'headers = {{ "{header_name}" = "2" }}\n'

    _assert_invalid_scenario(
        tmp_path,
        document,
        f"routes[1].steps[1].headers[{header_name!r}]: header is managed by the server",
    )


@pytest.mark.parametrize("header_name", ["Content-Length: 1", "X Client", "", "X-Сlient"])
def test_load_rejects_invalid_response_header_name(tmp_path: Path, header_name: str) -> None:
    document = _ROUTE_TOML + _STEP_TOML + f'headers = {{ "{header_name}" = "2" }}\n'

    _assert_invalid_scenario(
        tmp_path, document, f"routes[1].steps[1].headers[{header_name!r}]: invalid HTTP header name"
    )


def test_load_rejects_invalid_match_header_name(tmp_path: Path) -> None:
    document = _ROUTE_TOML + 'match.headers = { "X-Client:" = "app" }\n' + _STEP_TOML

    _assert_invalid_scenario(
        tmp_path, document, "routes[1].match.headers['X-Client:']: invalid HTTP header name"
    )


def test_load_accepts_header_name_with_http_token_punctuation(tmp_path: Path) -> None:
    document = _ROUTE_TOML + _STEP_TOML + 'headers = { "X_Debug!" = "app" }\n'
    scenario_path = _write_scenario_file(tmp_path, document)

    assert load_scenario(scenario_path).routes[0].steps[0].headers == {"X_Debug!": "app"}


@pytest.mark.parametrize("value_toml", [r"one\u0000two", r"one\u001ftwo", r"one\u007ftwo"])
def test_load_rejects_control_characters_in_header_value(tmp_path: Path, value_toml: str) -> None:
    document = _ROUTE_TOML + _STEP_TOML + f'headers = {{ "X-Debug" = "{value_toml}" }}\n'

    _assert_invalid_scenario(
        tmp_path, document, "routes[1].steps[1].headers['X-Debug']: invalid control character"
    )


def test_load_preserves_tab_in_header_value(tmp_path: Path) -> None:
    document = _ROUTE_TOML + _STEP_TOML + r'headers = { "X-Debug" = "one\ttwo" }'
    scenario_path = _write_scenario_file(tmp_path, document)

    assert load_scenario(scenario_path).routes[0].steps[0].headers == {"X-Debug": "one\ttwo"}


@pytest.mark.parametrize(
    ("header_entry_toml", "escaped_header_name"),
    [
        (r'"X-Client\rExtra" = "app"', r"X-Client\rExtra"),
        (r'"X-Client\nExtra" = "app"', r"X-Client\nExtra"),
        (r'"X-Client" = "app\rInjected"', "X-Client"),
        (r'"X-Client" = "app\nInjected"', "X-Client"),
    ],
)
@pytest.mark.parametrize("for_match", [False, True], ids=["response", "match"])
def test_load_rejects_header_line_breaks(
    tmp_path: Path, header_entry_toml: str, escaped_header_name: str, for_match: bool
) -> None:
    headers_toml = f"headers = {{ {header_entry_toml} }}\n"
    if for_match:
        document = _ROUTE_TOML + "match." + headers_toml + _STEP_TOML
        field = "routes[1].match.headers"
    else:
        document = _ROUTE_TOML + _STEP_TOML + headers_toml
        field = "routes[1].steps[1].headers"

    _assert_invalid_scenario(
        tmp_path,
        document,
        f"{field}['{escaped_header_name}']: header names and values cannot contain CR or LF",
    )


@pytest.mark.parametrize("status", [204, 205, 304])
def test_load_rejects_nonempty_body_for_bodyless_status(tmp_path: Path, status: int) -> None:
    document = _ROUTE_TOML + f'[[routes.steps]]\nstatus = {status}\nbody = " "\n'

    _assert_invalid_scenario(
        tmp_path, document, f"routes[1].steps[1].body: status {status} requires an empty body"
    )


@pytest.mark.parametrize(
    ("status", "body_field_toml", "expected_body", "expected_body_file"),
    [
        (204, "", "", None),
        (205, 'body = ""', "", None),
        (304, 'body_file = "not-created.txt"', None, "not-created.txt"),
        (599, 'body = "text"', "text", None),
    ],
)
def test_load_accepts_valid_status_and_body(
    tmp_path: Path,
    status: int,
    body_field_toml: str,
    expected_body: str | None,
    expected_body_file: str | None,
) -> None:
    document = _ROUTE_TOML + f"[[routes.steps]]\nstatus = {status}\n{body_field_toml}\n"
    scenario_path = _write_scenario_file(tmp_path, document)

    (step,) = load_scenario(scenario_path).routes[0].steps

    assert (step.status, step.body, step.body_file) == (status, expected_body, expected_body_file)
