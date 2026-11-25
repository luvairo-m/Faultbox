"""Local HTTP listener and placeholder responses."""

from __future__ import annotations

import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer


HOST = "127.0.0.1"


class _PlaceholderHandler(BaseHTTPRequestHandler):
    timeout = 5

    def do_GET(self) -> None:
        self.send_error(HTTPStatus.NOT_FOUND)

    do_POST = do_GET


class _LocalHTTPServer(HTTPServer):
    # On Windows, SO_REUSEADDR can allow a second server to bind to the same port.
    allow_reuse_address = sys.platform != "win32"


def create_server(port: int) -> HTTPServer:
    """Open a loopback listener for the caller to manage."""
    return _LocalHTTPServer((HOST, port), _PlaceholderHandler)
