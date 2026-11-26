"""Serve scenario responses over a local HTTP listener."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from faultbox.engine.models import AssignedResponse, RequestContext
from faultbox.engine.runtime import ScenarioEngine


HOST = "127.0.0.1"
MAX_REQUEST_BODY_BYTES = 1024 * 1024
BODY_PREVIEW_BYTES = 4096


@dataclass(frozen=True)
class RequestBodyPreview:
    """An unchanged body prefix for future request diagnostics."""

    data: bytes
    truncated: bool


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
    timeout = 5.0

    def _handle_scenario_request(self) -> None:
        self.request_body_preview = RequestBodyPreview(b"", False)
        # BaseHTTPRequestHandler collapses leading slashes in self.path.
        target = self.requestline.split()[1]

        try:
            path, query = _split_request_target(target)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid request target")
            return

        body_length = self._request_body_length()

        if body_length is None:
            return

        try:
            self.request_body_preview = self._read_request_body(body_length)
        except EOFError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Incomplete request body")
            return
        except TimeoutError:
            self.send_error(HTTPStatus.REQUEST_TIMEOUT, "Timed out reading request body")
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

    def _request_body_length(self) -> int | None:
        lengths = [value for name, value in self.headers.items() if name.lower() == "content-length"]

        if "Transfer-Encoding" in self.headers:
            if lengths:
                self.send_error(
                    HTTPStatus.BAD_REQUEST,
                    "Transfer-Encoding and Content-Length cannot be combined",
                )
            else:
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, "Transfer-Encoding is not supported")

            return None

        if "Expect" in self.headers:
            self.send_error(HTTPStatus.EXPECTATION_FAILED, "Expect is not supported")
            return None

        if not lengths:
            return 0

        if len(lengths) != 1:
            self.send_error(HTTPStatus.BAD_REQUEST, "Multiple Content-Length headers")
            return None

        value = lengths[0].strip(" \t")

        if not value.isascii() or not value.isdecimal():
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return None

        # Bound the conversion as well as the body, allowing any leading zeros.
        value = value.lstrip("0") or "0"

        if len(value) > len(str(MAX_REQUEST_BODY_BYTES)) or int(value) > MAX_REQUEST_BODY_BYTES:
            self.send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                f"Request body exceeds {MAX_REQUEST_BODY_BYTES} bytes",
            )
            return None

        return int(value)

    def _read_request_body(self, length: int) -> RequestBodyPreview:
        preview = bytearray()
        remaining = length
        deadline = monotonic() + self.timeout

        try:
            while remaining:
                wait_seconds = deadline - monotonic()

                if wait_seconds <= 0:
                    raise TimeoutError

                self.connection.settimeout(wait_seconds)

                # One socket read per iteration keeps slow input within the deadline.
                chunk = self.rfile.read1(min(remaining, 64 * 1024))
                if not chunk:
                    raise EOFError("Incomplete request body")

                remaining -= len(chunk)
                preview.extend(chunk[: BODY_PREVIEW_BYTES - len(preview)])
        finally:
            self.connection.settimeout(self.timeout)

        return RequestBodyPreview(bytes(preview), length > BODY_PREVIEW_BYTES)

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


class _LocalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, engine: ScenarioEngine) -> None:
        self.engine = engine
        super().__init__((HOST, port), _ScenarioHandler)


def create_server(port: int, engine: ScenarioEngine) -> ThreadingHTTPServer:
    """Open a loopback listener for the caller to manage."""
    return _LocalHTTPServer(port, engine)
