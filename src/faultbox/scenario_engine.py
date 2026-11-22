"""Assign scenario responses to sequential requests without performing I/O."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import repeat

from faultbox.models import ResponseStep, Route, Scenario


@dataclass(frozen=True)
class RequestContext:
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


@dataclass
class _RouteState:
    responses: Iterator[tuple[int, ResponseStep]]
    assignment_count: int = 0


class ScenarioEngine:
    """Keep independent response sequences for the routes of a loaded scenario."""

    def __init__(self, scenario: Scenario) -> None:
        self._routes_by_method_and_path: dict[tuple[str, str], list[Route]] = {}
        self._states: dict[str, _RouteState] = {}

        for route in scenario.routes:
            key = (route.method, route.path)
            self._routes_by_method_and_path.setdefault(key, []).append(route)
            self._states[route.id] = _RouteState(_generate_numbered_responses(route.steps))

    def next_response(self, request: RequestContext) -> AssignedResponse | None:
        """Assign the next step immediately, or return None for an unknown route."""
        candidates = self._routes_by_method_and_path.get((request.method, request.path))

        if candidates is None:
            return None

        # Until conditions are supported, use the first method/path candidate.
        route_id = candidates[0].id
        state = self._states[route_id]

        step_number, step = next(state.responses)

        state.assignment_count += 1
        body = step.body

        assert body is not None, "ScenarioEngine requires loaded response bodies"

        return AssignedResponse(
            route_id=route_id,
            step_number=step_number,
            assignment_number=state.assignment_count,
            status=step.status,
            headers=step.headers.copy(),
            body=body,
            delay_ms=step.delay_ms,
        )


def _generate_numbered_responses(
    steps: list[ResponseStep],
) -> Iterator[tuple[int, ResponseStep]]:
    """Yield one-based step numbers with their steps, repeating the last forever."""
    for step_number, step in enumerate(steps, start=1):
        for _ in range(step.repeat):
            yield step_number, step

    yield from repeat((len(steps), steps[-1]))
