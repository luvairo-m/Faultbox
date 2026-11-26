from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from http.client import HTTPConnection, HTTPMessage
from pathlib import Path
from socket import create_connection
from threading import Thread

import pytest

from faultbox.engine.runtime import ScenarioEngine
from faultbox.scenario.loader import load_scenario
from faultbox.server import HOST, create_server


@contextmanager
def _running_server(scenario_path: Path) -> Iterator[int]:
    engine = ScenarioEngine(load_scenario(scenario_path))

    with create_server(0, engine) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            worker.join()


def _request(
    port: int,
    method: str,
    target: str,
    *,
    headers: Mapping[str, str | bytes] | None = None,
    body: bytes | None = None,
) -> tuple[int, HTTPMessage, bytes]:
    with closing(HTTPConnection(HOST, port, timeout=2)) as connection:
        connection.request(method, target, body=body, headers=headers or {})

        with connection.getresponse() as response:
            return response.status, response.headers, response.read()


@pytest.mark.parametrize(
    ("target", "headers", "expected_status", "expected_body"),
    [
        (
            "/users?role=guest&%72ole=%61dmin",
            {"x-cLiEnT": "backend"},
            200,
            b'{"role":"admin","permissions":["read","write"]}',
        ),
        ("/users?role=guest", {}, 200, b'{"role":"guest","permissions":["read"]}'),
        ("/users?role=admin", {}, 400, b"Unsupported role or missing X-Client header"),
        ("/users", {}, 400, b"Unsupported role or missing X-Client header"),
    ],
    ids=["admin", "guest", "fallback-missing-header", "fallback-missing-query"],
)
def test_users_match_readme_routes(
    readme_scenario_path: Path,
    target: str,
    headers: dict[str, str],
    expected_status: int,
    expected_body: bytes,
) -> None:
    with _running_server(readme_scenario_path) as port:
        status, response_headers, body = _request(port, "GET", target, headers=headers)

    assert (status, body) == (expected_status, expected_body)
    if expected_status == 200:
        assert response_headers["Content-Type"] == "application/json"


def test_payments_sequences_are_isolated_and_serve_body_file(readme_scenario_path: Path) -> None:
    payment_file = readme_scenario_path.parent / "responses" / "payment.json"
    payment_body = payment_file.read_bytes()

    with _running_server(readme_scenario_path) as port:
        for method, target in [("GET", "/payments"), ("POST", "/payments/")]:
            status, _, _ = _request(port, method, target, headers={"X-Test-Case-ID": "retry-a"})
            assert status == 404

        for expected_status, expected_body in [
            (500, b"Temporary failure"),
            (500, b"Temporary failure"),
            (200, payment_body),
        ]:
            for test_case in ("retry-a", "retry-b"):
                status, headers, body = _request(
                    port,
                    "POST",
                    "/payments?ignored=1",
                    headers={"x-test-case-id": test_case},
                    body=b"arbitrary request body",
                )

                assert (status, body) == (expected_status, expected_body)
                if expected_status == 200:
                    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_exact_path_and_blank_query_with_utf8_response(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        """\
[[routes]]
id = "exact-path"
method = "GET"
path = "//items/a%2Fb"
match = { query = { filter = "" } }

[[routes.steps]]
status = 201
body = "Готово"
headers = { "X-Result" = "Готово" }

[[routes.steps]]
status = 200
""",
        encoding="utf-8",
    )

    expected_body = "Готово".encode("utf-8")
    with _running_server(scenario_path) as port:
        for target in ("//items/a%2Fb", "/items/a%2Fb?filter=", "//items/a/b?filter="):
            status, _, _ = _request(port, "GET", target)
            assert status == 404

        status, headers, body = _request(port, "GET", "//items/a%2Fb?filter=")

    assert (status, body) == (201, expected_body)
    assert headers["Content-Length"] == str(len(expected_body))
    assert headers["X-Result"].encode("latin-1") == expected_body


@pytest.mark.parametrize("header_value", ["café".encode("utf-8"), b"caf\xe9"])
def test_matches_non_ascii_header(tmp_path: Path, header_value: bytes) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        """\
[[routes]]
id = "items"
method = "GET"
path = "/items"
match = { headers = { "X-Label" = "café" } }

[[routes.steps]]
status = 200
""",
        encoding="utf-8",
    )

    with _running_server(scenario_path) as port:
        status, _, _ = _request(port, "GET", "/items", headers={"x-lAbEl": header_value})

    assert status == 200


def test_invalid_targets_do_not_consume_root_response(tmp_path: Path) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        """\
[[routes]]
id = "root"
method = "GET"
path = "/"

[[routes.steps]]
status = 201

[[routes.steps]]
status = 200
""",
        encoding="utf-8",
    )

    with _running_server(scenario_path) as port:
        for target in ("http://", "http://localhost/#fragment", "*"):
            status, _, _ = _request(port, "GET", target)
            assert status == 400

        status, _, _ = _request(port, "GET", f"http://{HOST}:{port}")
        assert status == 201

        status, _, _ = _request(port, "GET", "/")
        assert status == 200


@pytest.mark.parametrize(
    ("status_code", "length_headers"),
    [(204, []), (205, [b"content-length: 0"]), (304, [])],
)
def test_sends_empty_responses_without_incorrect_length(
    tmp_path: Path, status_code: int, length_headers: list[bytes]
) -> None:
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        f"""\
[[routes]]
id = "empty"
method = "GET"
path = "/empty"

[[routes.steps]]
status = {status_code}
""",
        encoding="utf-8",
    )

    with _running_server(scenario_path) as port:
        with create_connection((HOST, port), timeout=2) as connection:
            connection.sendall(b"GET /empty HTTP/1.1\r\nHost: localhost\r\n\r\n")
            with connection.makefile("rb") as stream:
                response = stream.read()

    headers, separator, body = response.partition(b"\r\n\r\n")
    assert int(headers.split()[1]) == status_code
    assert separator and body == b""
    assert [
        line for line in headers.lower().splitlines() if line.startswith(b"content-length:")
    ] == length_headers
