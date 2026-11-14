"""Validate scenario models independently of their input format."""

from __future__ import annotations

from string import ascii_letters, digits

from faultbox.models import HttpMethod, ResponseStep, Route, Scenario


_NO_BODY_STATUSES = {204, 205, 304}
_SERVER_MANAGED_HEADERS = {"content-length", "transfer-encoding", "connection"}
# HTTP field names use the token characters defined in RFC 9110.
_HEADER_NAME_CHARS = frozenset(ascii_letters + digits + "!#$%&'*+-.^_`|~")

_RouteVariantKey = tuple[HttpMethod, str, frozenset[tuple[str, str]], frozenset[tuple[str, str]]]


def validate_scenario(scenario: Scenario) -> None:
    """Check rules for typed scenario data and report the first violation."""
    if not scenario.routes:
        raise ValueError("routes: expected a non-empty array")

    seen_route_ids: set[str] = set()
    seen_variant_keys: set[_RouteVariantKey] = set()

    for route_number, route in enumerate(scenario.routes, start=1):
        field = f"routes[{route_number}]"
        _validate_route(route, field)

        if route.id in seen_route_ids:
            raise ValueError(f"{field}.id: duplicate route id {route.id!r}")

        # Frozen sets let us compare conditions independently of their order.
        variant_key = (
            route.method,
            route.path,
            frozenset((name.lower(), value) for name, value in route.match.headers.items()),
            frozenset(route.match.query.items()),
        )

        if variant_key in seen_variant_keys:
            raise ValueError(
                f"{field}.match: duplicate route variant for {route.method} {route.path}"
            )

        seen_route_ids.add(route.id)
        seen_variant_keys.add(variant_key)


def _validate_route(route: Route, field: str) -> None:
    _validate_path(route.path, f"{field}.path")

    if not route.steps:
        raise ValueError(f"{field}.steps: expected a non-empty array")

    for step_number, step in enumerate(route.steps, start=1):
        _validate_step(step, f"{field}.steps[{step_number}]")

    _validate_match_headers(route.match.headers, f"{field}.match.headers")


def _validate_path(path: str, field: str) -> None:
    if not path.startswith("/"):
        raise ValueError(f"{field}: expected a path starting with '/'")

    if "?" in path or "#" in path:
        raise ValueError(f"{field}: cannot contain a query or fragment")

    if any(ord(char) <= 32 or char == "\x7f" for char in path):
        raise ValueError(f"{field}: cannot contain spaces or control characters")

    if path.startswith("/__faultbox/"):
        raise ValueError(f"{field}: prefix /__faultbox/ is reserved")


def _validate_match_headers(headers: dict[str, str], field: str) -> None:
    seen_header_names: set[str] = set()

    for name, value in headers.items():
        header_field = f"{field}[{name!r}]"
        _validate_header(name, value, header_field)

        normalized_name = name.lower()
        if normalized_name == "x-test-case-id":
            raise ValueError(f"{header_field}: header is reserved for test isolation")

        if normalized_name in seen_header_names:
            raise ValueError(f"{header_field}: duplicate header name (ignoring case)")

        seen_header_names.add(normalized_name)


def _validate_response_headers(headers: dict[str, str], field: str) -> None:
    for name, value in headers.items():
        header_field = f"{field}[{name!r}]"
        _validate_header(name, value, header_field)

        if name.lower() in _SERVER_MANAGED_HEADERS:
            raise ValueError(f"{header_field}: header is managed by the server")


def _validate_header(name: str, value: str, field: str) -> None:
    if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
        raise ValueError(f"{field}: header names and values cannot contain CR or LF")

    if not name or any(char not in _HEADER_NAME_CHARS for char in name):
        raise ValueError(f"{field}: invalid HTTP header name")

    if any((ord(char) < 32 and char != "\t") or char == "\x7f" for char in value):
        raise ValueError(f"{field}: invalid control character in HTTP header value")


def _validate_step(step: ResponseStep, field: str) -> None:
    # Python's int annotation also accepts bool, so models need this check too.
    for field_name, field_value in (
        ("status", step.status),
        ("delay_ms", step.delay_ms),
        ("repeat", step.repeat),
    ):
        if isinstance(field_value, bool):
            raise ValueError(f"{field}.{field_name}: expected an integer")

    if not 200 <= step.status <= 599:
        raise ValueError(f"{field}.status: expected a status between 200 and 599")

    if step.delay_ms < 0:
        raise ValueError(f"{field}.delay_ms: expected an integer greater than or equal to 0")

    if step.repeat < 1:
        raise ValueError(f"{field}.repeat: expected an integer greater than or equal to 1")

    _validate_response_headers(step.headers, f"{field}.headers")
    validate_response_body(step.status, step.body, f"{field}.body")


def validate_response_body(status: int, body: str | None, field: str) -> None:
    """Check the body rule for a response with a validated status."""
    if status in _NO_BODY_STATUSES and body:
        raise ValueError(f"{field}: status {status} requires an empty body")
