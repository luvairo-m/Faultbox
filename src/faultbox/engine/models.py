"""Request and response types for the scenario engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """Request data for route matching and test isolation.

    The caller passes the exact path separately from the decoded query parameters.
    """

    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class AssignedResponse:
    route_id: str
    step_number: int
    assignment_number: int
    status: int
    headers: dict[str, str]
    body: str
    delay_ms: int
