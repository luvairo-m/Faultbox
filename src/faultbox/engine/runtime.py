"""Assign scenario responses to sequential requests without performing I/O."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import repeat

from faultbox.engine.models import AssignedResponse, RequestContext
from faultbox.scenario.models import ResponseStep, Route, Scenario


@dataclass
class _RouteState:
    responses: Iterator[tuple[int, ResponseStep]]
    assignment_count: int = 0


class ScenarioEngine:
    """Keep independent response sequences per route and test case."""

    def __init__(self, scenario: Scenario) -> None:
        self._routes_by_method_and_path: dict[tuple[str, str], list[Route]] = {}
        self._states: dict[tuple[str, str | None], _RouteState] = {}

        for route in scenario.routes:
            key = (route.method, route.path)
            self._routes_by_method_and_path.setdefault(key, []).append(route)

    def next_response(self, request: RequestContext) -> AssignedResponse | None:
        """Assign the next step immediately, or return None if no route matches."""
        headers = {name.lower(): value for name, value in request.headers.items()}
        route = self._select_route(request, headers)

        if route is None:
            return None

        test_case_id = headers.get("x-test-case-id", "").strip(" \t") or None
        state_key = (route.id, test_case_id)
        state = self._states.get(state_key)

        if state is None:
            state = _RouteState(self._generate_numbered_responses(route.steps))
            self._states[state_key] = state

        step_number, step = next(state.responses)
        state.assignment_count += 1

        body = step.body
        assert body is not None, "ScenarioEngine requires loaded response bodies"

        return AssignedResponse(
            route_id=route.id,
            step_number=step_number,
            assignment_number=state.assignment_count,
            status=step.status,
            headers=step.headers.copy(),
            body=body,
            delay_ms=step.delay_ms,
        )

    def _select_route(self, request: RequestContext, headers: dict[str, str]) -> Route | None:
        candidates = self._routes_by_method_and_path.get((request.method, request.path))

        if candidates is None:
            return None

        for route in candidates:
            if not all(
                headers.get(name.lower()) == value for name, value in route.match.headers.items()
            ):
                continue

            if all(value in request.query.get(name, ()) for name, value in route.match.query.items()):
                return route

        return None

    @staticmethod
    def _generate_numbered_responses(
        steps: list[ResponseStep],
    ) -> Iterator[tuple[int, ResponseStep]]:
        """Yield one-based step numbers with their steps, repeating the last forever."""
        for step_number, step in enumerate(steps, start=1):
            for _ in range(step.repeat):
                yield step_number, step

        yield from repeat((len(steps), steps[-1]))
