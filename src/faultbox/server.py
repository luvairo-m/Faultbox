"""Serve scenario responses over a local HTTP listener."""

from __future__ import annotations

import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from faultbox.engine.models import AssignedResponse, RequestContext
from faultbox.engine.runtime import ScenarioEngine


HOST = "127.0.0.1"


def _split_request_target(target: str) -> tuple[str, str]:
    if "#" in target:
        raise ValueError("request target cannot contain a fragment")

    if target.startswith("/"):
        path, _, query = target.partition("?")
        return path, query

    url = urlsplit(target)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError("expected a path or an absolute HTTP URL")

    return url.path or "/", url.query


def _decode_request_header(value: str) -> str:
    # http.server decodes header bytes as Latin-1, which preserves the original bytes.
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return value


class _ScenarioHandler(BaseHTTPRequestHandler):
    server: _LocalHTTPServer
    timeout = 5

    def _handle_scenario_request(self) -> None:
        # BaseHTTPRequestHandler collapses leading slashes in self.path.
        target = self.requestline.split()[1]

        try:
            path, query = _split_request_target(target)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid request target")
            return

        request = RequestContext(
            method=self.command,
            path=path,
            headers={
                name.lower(): _decode_request_header(value) for name, value in self.headers.items()
            },
            query=parse_qs(query, keep_blank_values=True),
        )

        response = self.server.engine.next_response(request)

        if response is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        self._send_scenario_response(response)

    do_GET = _handle_scenario_request
    do_POST = _handle_scenario_request

    def _send_scenario_response(self, response: AssignedResponse) -> None:
        body = response.body.encode("utf-8")

        self.log_request(response.status)
        self.send_response_only(response.status)

        if not any(name.lower() == "date" for name in response.headers):
            self.send_header("Date", self.date_time_string())

        for name, value in response.headers.items():
            self.send_header(name, value.encode("utf-8").decode("latin-1"))

        if response.status not in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED):
            self.send_header("Content-Length", str(len(body)))

        self.send_header("Connection", "close")
        self.end_headers()

        if body:
            self.wfile.write(body)


class _LocalHTTPServer(HTTPServer):
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, engine: ScenarioEngine) -> None:
        self.engine = engine
        super().__init__((HOST, port), _ScenarioHandler)


def create_server(port: int, engine: ScenarioEngine) -> HTTPServer:
    """Open a loopback listener for the caller to manage."""
    return _LocalHTTPServer(port, engine)
