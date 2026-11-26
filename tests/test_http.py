from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from http.client import HTTPConnection, HTTPMessage
from pathlib import Path
from socket import SHUT_WR, create_connection, socket
from threading import Event, Thread

import pytest

from faultbox import server as http_server
from faultbox.engine.runtime import ScenarioEngine
from faultbox.scenario.loader import load_scenario
from faultbox.server import HOST, create_server


DELAY_SCENARIO = Path(__file__).resolve().parents[1] / "examples" / "delay.toml"


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


def _raw_request(port: int, request: bytes, *, end_body: bool = False) -> bytes:
    with create_connection((HOST, port), timeout=2) as connection:
        connection.sendall(request)
        if end_body:
            connection.shutdown(SHUT_WR)

        with connection.makefile("rb") as stream:
            return stream.read()


@pytest.fixture
def request_scenario_path(tmp_path: Path) -> Path:
    scenario_path = tmp_path / "scenario.toml"
    routes = []
    for method in ("GET", "POST"):
        routes.append(
            f'''\
[[routes]]
id = "{method.lower()}-body"
method = "{method}"
path = "/body"

[[routes.steps]]
status = 201
body = "first"

[[routes.steps]]
status = 202
body = "next"
'''
        )

    scenario_path.write_text("\n".join(routes), encoding="utf-8")
    return scenario_path


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


def test_other_requests_finish_while_first_step_is_delayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = Event()
    release = Event()
    intervals: list[float | None] = []

    class ControlledWait(Event):
        def wait(self, timeout: float | None = None) -> bool:
            intervals.append(timeout)
            waiting.set()
            assert release.wait(timeout=5)
            return False

    monkeypatch.setattr(http_server, "Event", ControlledWait)
    monkeypatch.setattr(http_server, "TIMEOUT_MAX", 2)

    with _running_server(DELAY_SCENARIO) as port:
        with closing(HTTPConnection(HOST, port, timeout=2)) as first:
            first.request("GET", "/slow")

            try:
                assert waiting.wait(timeout=2)
                status, _, body = _request(port, "GET", "/slow")
                assert (status, body) == (200, b"Next response")
                status, _, body = _request(port, "GET", "/fast")
                assert (status, body) == (200, b"Ready")
            finally:
                release.set()

            with first.getresponse() as response:
                assert (response.status, response.read()) == (200, b"Delayed response")

    assert intervals == [2.0, 1.0]


def test_client_times_out_and_server_close_interrupts_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    wait_started = Event()

    class ObservedWait(Event):
        def wait(self, timeout: float | None = None) -> bool:
            wait_started.set()
            return super().wait(timeout)

    monkeypatch.setattr(http_server, "Event", ObservedWait)

    with socket() as client:
        with _running_server(DELAY_SCENARIO) as port:
            client.connect((HOST, port))
            client.sendall(b"GET /slow HTTP/1.0\r\n\r\n")
            assert wait_started.wait(timeout=2)

            client.settimeout(0.1)
            with pytest.raises(TimeoutError):
                client.recv(1)

        client.settimeout(2)
        assert client.recv(1) == b""


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
    [(200, [b"content-length: 0"]), (204, []), (205, [b"content-length: 0"]), (304, [])],
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
    assert b"connection: close" in headers.lower().splitlines()
    assert not any(line.startswith(b"transfer-encoding:") for line in headers.lower().splitlines())


@pytest.mark.parametrize("body_source", ["body", "body_file"])
def test_preserves_response_bytes_and_custom_headers(
    tmp_path: Path, body_source: str
) -> None:
    body_text = '{"message": "Ошибка 🌍",\ninvalid JSON'
    scenario_path = tmp_path / "scenario.toml"
    if body_source == "body_file":
        (tmp_path / "response.txt").write_bytes(body_text.encode("utf-8"))
        body_field = 'body_file = "response.txt"'
    else:
        body_field = f"body = '''{body_text}'''"

    scenario_path.write_text(
        f'''\
[[routes]]
id = "raw"
method = "GET"
path = "/raw"

[[routes.steps]]
status = 200
{body_field}
headers = {{ "Content-Type" = "application/json", "dAtE" = "Thu, 01 Jan 1970 00:00:00 GMT" }}
''',
        encoding="utf-8",
    )

    with _running_server(scenario_path) as port:
        status, headers, body = _request(port, "GET", "/raw")

    assert (status, body) == (200, body_text.encode("utf-8"))
    assert headers.get_all("Content-Length") == [str(len(body))]
    assert headers.get_all("Date") == ["Thu, 01 Jan 1970 00:00:00 GMT"]
    assert headers.get_all("Content-Type") == ["application/json"]
    assert headers.get_all("Connection") == ["close"]
    assert headers.get_all("Transfer-Encoding") is None


@pytest.mark.parametrize(
    ("request_headers", "expected_status", "message"),
    [
        (b"Content-Length: -1\r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: +1\r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: text\r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: \r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: 1, 1\r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: \xb2\r\n", 400, b"Invalid Content-Length"),
        (b"Content-Length: 1\r\ncOnTeNt-LeNgTh: 1\r\n", 400, b"Multiple Content-Length"),
        (b"Transfer-Encoding: chunked\r\n", 501, b"Transfer-Encoding is not supported"),
        (
            b"transfer-encoding: chunked\r\nContent-Length: 1\r\n",
            400,
            b"Transfer-Encoding and Content-Length cannot be combined",
        ),
        (b"Content-Length: 1048577\r\n", 413, b"Request body exceeds 1048576 bytes"),
        pytest.param(
            b"Content-Length: " + b"9" * 5000 + b"\r\n",
            413,
            b"Request body exceeds 1048576 bytes",
            id="oversized-number",
        ),
        (b"Expect: 100-continue\r\nContent-Length: 1\r\n", 417, b"Expect is not supported"),
    ],
)
def test_rejects_unsupported_body_framing_before_reading_or_assigning(
    request_scenario_path: Path, request_headers: bytes, expected_status: int, message: bytes
) -> None:
    request = b"POST /body HTTP/1.1\r\nHost: localhost\r\n" + request_headers + b"\r\n"
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, request)
        status, _, body = _request(port, "POST", "/body")

    headers, separator, error_body = response.partition(b"\r\n\r\n")
    assert int(headers.split()[1]) == expected_status
    assert b"connection: close" in headers.lower().splitlines()
    assert separator == b"\r\n\r\n" and message in error_body
    assert (status, body) == (201, b"first")


@pytest.mark.parametrize(
    ("method", "request_body"),
    [
        ("POST", b""),
        ("GET", "Кириллица 🌍".encode("utf-8")),
        ("POST", b"\x00\xff\xfe"),
        ("POST", b"x" * 4096),
        ("POST", b"x" * 4095 + "🌍".encode("utf-8")),
        ("POST", b"x" * 1048576),
    ],
    ids=["empty", "unicode", "binary", "preview-limit", "split-unicode", "body-limit"],
)
def test_reads_body_and_keeps_only_a_bounded_preview(
    request_scenario_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, request_body: bytes
) -> None:
    previews: list[http_server.RequestBodyPreview] = []

    def capture_preview(
        handler: http_server._ScenarioHandler, code: int | str = "-", size: int | str = "-"
    ) -> None:
        previews.append(handler.request_body_preview)

    monkeypatch.setattr(http_server._ScenarioHandler, "log_request", capture_preview)
    with _running_server(request_scenario_path) as port:
        status, _, body = _request(port, method, "/body", body=request_body)

    assert (status, body) == (201, b"first")
    assert len(previews) == 1
    assert previews[0].data == request_body[:4096]
    assert previews[0].truncated == (len(request_body) > 4096)


@pytest.mark.parametrize("failure", ["timeout", "early-eof", "deadline"])
def test_incomplete_body_does_not_consume_a_step(
    request_scenario_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(http_server._ScenarioHandler, "timeout", 0.1)
    if failure == "deadline":
        # Even with incoming data, the next iteration must respect the total deadline.
        read_times = iter([0.0, 0.0, 1.0])
        monkeypatch.setattr(http_server, "monotonic", lambda: next(read_times, 1.0))

    request = b"POST /body HTTP/1.1\r\nHost: localhost\r\nContent-Length: 4097\r\n\r\n"
    request += b"x" * 4096
    end_body = failure == "early-eof"
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, request, end_body=end_body)
        status, _, body = _request(port, "POST", "/body")

    assert int(response.split()[1]) == (400 if end_body else 408)
    message = b"Incomplete request body" if end_body else b"Timed out reading request body"
    assert message in response
    assert (status, body) == (201, b"first")


@pytest.mark.parametrize("method", ["PUT", "HEAD"])
def test_unsupported_methods_return_501(request_scenario_path: Path, method: str) -> None:
    with _running_server(request_scenario_path) as port:
        status, headers, _ = _request(port, method, "/body")
        next_status, _, next_body = _request(port, "POST", "/body")

    assert status == 501
    assert headers["Connection"] == "close"
    assert (next_status, next_body) == (201, b"first")


def test_missing_length_means_empty_body(request_scenario_path: Path) -> None:
    request = b"POST /body HTTP/1.1\r\nHost: localhost\r\n\r\n"
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, request)

    headers, _, body = response.partition(b"\r\n\r\n")
    assert int(headers.split()[1]) == 201
    assert body == b"first"


def test_headerless_get_still_serves_response(request_scenario_path: Path) -> None:
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, b"GET /body\r\n\r\n")

    assert response == b"first"


def test_content_length_accepts_leading_zeros(request_scenario_path: Path) -> None:
    request = b"POST /body HTTP/1.1\r\nHost: localhost\r\nContent-Length: "
    request += b"0" * 5000 + b"1\r\n\r\nx"
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, request)

    headers, _, body = response.partition(b"\r\n\r\n")
    assert int(headers.split()[1]) == 201
    assert body == b"first"


def test_closes_after_one_request_even_with_keep_alive(request_scenario_path: Path) -> None:
    first_request = (
        b"POST /body HTTP/1.1\r\nHost: localhost\r\n"
        b"Content-Length: 4\r\nConnection: keep-alive\r\n\r\ndata"
    )
    second_request = b"POST /body HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n"
    with _running_server(request_scenario_path) as port:
        response = _raw_request(port, first_request + second_request)
        next_status, _, next_body = _request(port, "POST", "/body")

    headers, _, body = response.partition(b"\r\n\r\n")
    assert int(headers.split()[1]) == 201
    assert b"connection: close" in headers.lower().splitlines()
    assert body == b"first"
    assert (next_status, next_body) == (202, b"next")
